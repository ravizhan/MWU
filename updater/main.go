package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/mholt/archives"
	"github.com/zeebo/xxh3"
)

const (
	exitCodeSelfUpdate = 10
	exitCodeError      = 1
	defaultChangesFile = "changes.json"
)

type Config struct {
	Archive    string
	WebhookURL string
	RestartCmd string
}

type UpdateResult struct {
	Status          string `json:"status"`
	Message         string `json:"message,omitempty"`
	RestartRequired bool   `json:"restart_required"`
}

func main() {
	logFile, _ := os.OpenFile("updater.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if logFile != nil {
		log.SetOutput(logFile)
	}

	cfg := parseFlags()
	ctx := context.Background()

	if cfg.Archive == "" {
		fail("Missing -archive argument")
	}
	if cfg.WebhookURL == "" {
		fail("Missing -webhook argument")
	}
	if cfg.RestartCmd == "" {
		fail("Missing -restart-cmd argument")
	}

	installDir, err := os.Getwd()
	if err != nil {
		fail("Failed to get working directory: %v", err)
	}

	extractDir := filepath.Join(installDir, "update_temp")
	_ = os.RemoveAll(extractDir)
	if err := os.MkdirAll(extractDir, 0o755); err != nil {
		fail("Failed to create temp dir: %v", err)
	}

	log.Printf("正在将 %s 解压到 %s", cfg.Archive, extractDir)
	if err := extractArchive(ctx, cfg.Archive, extractDir); err != nil {
		fail("Failed to extract archive: %v", err)
	}

	log.Println("检查自更新...")
	if performedSelfUpdate, err := handleSelfUpdate(installDir, extractDir); err != nil {
		fail("Self update failed: %v", err)
	} else if performedSelfUpdate {
		log.Println("已执行自更新。以代码 10 退出。")
		os.RemoveAll(extractDir)
		os.Exit(exitCodeSelfUpdate)
	}

	log.Println("通知主程序退出...")
	if err := notifyShutdown(cfg.WebhookURL); err != nil {
		log.Printf("警告：通知关闭失败：%v。", err)
	} else {
		time.Sleep(2 * time.Second)
	}

	log.Println("等待文件锁释放...")
	if err := waitForLocks(installDir, cfg.RestartCmd); err != nil {
		fail("Could not acquire file locks: %v", err)
	}

	log.Println("计算更改...")
	changes, err := getChanges(installDir, extractDir)
	if err != nil {
		fail("Failed to get changes: %v", err)
	}

	log.Println("应用更新...")
	if err := applyChanges(installDir, extractDir, changes); err != nil {
		fail("Failed to apply changes: %v", err)
	}

	changesPath := filepath.Join(installDir, defaultChangesFile)
	writeChanges(changesPath, changes)

	os.RemoveAll(extractDir)
	os.Remove(cfg.Archive)

	log.Printf("重启主程序：%s", cfg.RestartCmd)
	if err := restartMain(cfg.RestartCmd); err != nil {
		log.Printf("Failed to restart main program: %v", err)
	}

	log.Println("更新完成。")
	outputJSON(UpdateResult{
		Status:          "success",
		Message:         "更新成功完成",
		RestartRequired: true,
	})
}

func parseFlags() Config {
	cfg := Config{}
	flag.StringVar(&cfg.Archive, "archive", "", "更新包路径（zip/7z）")
	flag.StringVar(&cfg.WebhookURL, "webhook", "", "用于请求主程序关闭的URL")
	flag.StringVar(&cfg.RestartCmd, "restart-cmd", "", "重启主程序的命令")
	flag.Parse()
	return cfg
}

func extractArchive(ctx context.Context, archivePath, destDir string) error {
	file, err := os.Open(archivePath)
	if err != nil {
		return err
	}
	defer file.Close()

	format, reader, err := archives.Identify(ctx, archivePath, file)
	if err != nil {
		return err
	}
	extractor, ok := format.(archives.Extractor)
	if !ok {
		return errors.New("不支持的归档格式")
	}

	return extractor.Extract(ctx, reader, func(ctx context.Context, f archives.FileInfo) error {
		if f.NameInArchive == "" {
			return nil
		}
		pathInArchive := f.NameInArchive
		if runtime.GOOS == "windows" {
			pathInArchive = strings.ReplaceAll(pathInArchive, "\\", "/")
		}

		outPath, err := safeJoin(destDir, pathInArchive)
		if err != nil {
			return err
		}
		if f.IsDir() {
			return os.MkdirAll(outPath, 0o755)
		}

		if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
			return err
		}

		outFile, err := os.OpenFile(outPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, f.Mode())
		if err != nil {
			return err
		}
		defer outFile.Close()

		rc, err := f.Open()
		if err != nil {
			return err
		}
		defer rc.Close()

		_, err = io.Copy(outFile, rc)
		return err
	})
}

func handleSelfUpdate(installDir, extractDir string) (bool, error) {
	exePath, err := os.Executable()
	if err != nil {
		return false, err
	}

	relPath, err := filepath.Rel(installDir, exePath)
	if err != nil {
		return false, nil
	}

	candidate := filepath.Join(extractDir, relPath)
	if _, err := os.Stat(candidate); os.IsNotExist(err) {
		candidate = filepath.Join(extractDir, filepath.Base(exePath))
	}

	if _, err := os.Stat(candidate); err != nil {
		return false, nil
	}

	currentHash, _ := hashFile(exePath)
	candidateHash, _ := hashFile(candidate)

	if currentHash == candidateHash {
		return false, nil
	}

	oldPath := exePath + ".old"
	_ = os.Remove(oldPath)

	if err := os.Rename(exePath, oldPath); err != nil {
		return false, fmt.Errorf("移动当前可执行文件失败：%w", err)
	}

	if err := copyFile(candidate, exePath, 0755); err != nil {
		_ = os.Rename(oldPath, exePath)
		return false, fmt.Errorf("复制新可执行文件失败：%w", err)
	}

	return true, nil
}

func notifyShutdown(urlStr string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", urlStr, nil)
	if err != nil {
		return err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("服务器返回 %d", resp.StatusCode)
	}
	return nil
}

func waitForLocks(installDir, restartCmd string) error {
	deadline := time.Now().Add(30 * time.Second)
	executable := strings.TrimSpace(restartCmd)

	var path string
	if filepath.IsAbs(executable) {
		path = executable
	} else {
		path = filepath.Join(installDir, executable)
	}

	for time.Now().Before(deadline) {
		if _, err := os.Stat(path); err != nil {
			return nil
		}
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0644)
		if err == nil {
			f.Close()
			return nil
		}
		time.Sleep(1 * time.Second)
	}
	return errors.New("等待文件锁超时")
}

type ChangeLog struct {
	Added    []string `json:"added"`
	Deleted  []string `json:"deleted"`
	Modified []string `json:"modified"`
}

func getChanges(installDir, extractDir string) (ChangeLog, error) {
	changesPath := filepath.Join(extractDir, defaultChangesFile)
	changes := ChangeLog{
		Added:    []string{},
		Deleted:  []string{},
		Modified: []string{},
	}

	if _, err := os.Stat(changesPath); err == nil {
		data, err := os.ReadFile(changesPath)
		if err != nil {
			return changes, err
		}
		if err := json.Unmarshal(data, &changes); err != nil {
			return changes, err
		}
		if changes.Added == nil {
			changes.Added = []string{}
		}
		if changes.Deleted == nil {
			changes.Deleted = []string{}
		}
		if changes.Modified == nil {
			changes.Modified = []string{}
		}
		return changes, nil
	}

	type fileInfo struct {
		path string
		rel  string
	}

	type localChanges struct {
		added    []string
		modified []string
	}

	pkgFiles := make(chan fileInfo, 100)
	pkgFileMap := make(map[string]bool)
	var mapMu sync.Mutex

	numWorkers := runtime.NumCPU()
	var wg sync.WaitGroup

	// 使用通道收集每个 worker 的结果
	results := make(chan localChanges, numWorkers)

	go func() {
		filepath.WalkDir(extractDir, func(path string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil
			}
			rel, _ := filepath.Rel(extractDir, path)
			rel = filepath.ToSlash(rel)
			if rel == defaultChangesFile || rel == filepath.Base(os.Args[0]) {
				return nil
			}

			mapMu.Lock()
			pkgFileMap[rel] = true
			mapMu.Unlock()

			pkgFiles <- fileInfo{path, rel}
			return nil
		})
		close(pkgFiles)
	}()

	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			local := localChanges{
				added:    make([]string, 0),
				modified: make([]string, 0),
			}

			for f := range pkgFiles {
				targetPath := filepath.Join(installDir, f.rel)
				if _, err := os.Stat(targetPath); err != nil {
					local.added = append(local.added, f.rel)
					continue
				}

				h1, _ := hashFile(f.path)
				h2, _ := hashFile(targetPath)
				if h1 != h2 {
					local.modified = append(local.modified, f.rel)
				}
			}

			results <- local
		}()
	}

	// 等待所有 worker 完成并关闭结果通道
	go func() {
		wg.Wait()
		close(results)
	}()

	// 合并所有结果
	for local := range results {
		changes.Added = append(changes.Added, local.added...)
		changes.Modified = append(changes.Modified, local.modified...)
	}

	filepath.WalkDir(installDir, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(installDir, path)
		rel = filepath.ToSlash(rel)

		if strings.HasPrefix(rel, "config/") ||
			rel == "update_temp" ||
			strings.HasPrefix(rel, "update_temp/") ||
			strings.HasPrefix(rel, "debug/") ||
			rel == filepath.Base(os.Args[0]) ||
			rel == "updater.log" ||
			strings.HasSuffix(rel, ".old") ||
			rel == defaultChangesFile {
			return nil
		}

		mapMu.Lock()
		exists := pkgFileMap[rel]
		mapMu.Unlock()

		if !exists {
			changes.Deleted = append(changes.Deleted, rel)
		}
		return nil
	})

	return changes, nil
}

func applyChanges(installDir, extractDir string, changes ChangeLog) error {
	for _, rel := range append(changes.Added, changes.Modified...) {
		src := filepath.Join(extractDir, rel)
		dst := filepath.Join(installDir, rel)

		if rel == filepath.Base(os.Args[0]) || rel == defaultChangesFile {
			continue
		}

		if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
			return err
		}

		if err := copyFile(src, dst, 0755); err != nil {
			return err
		}
	}

	for _, rel := range changes.Deleted {
		dst := filepath.Join(installDir, rel)
		_ = os.Remove(dst)
	}

	return nil
}

func restartMain(cmdStr string) error {
	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.Command("cmd", "/c", "start", "/b", "cmd", "/c", cmdStr)
	} else {
		cmd = exec.Command("sh", "-c", cmdStr+" &")
	}
	return cmd.Start()
}

func writeChanges(path string, changes ChangeLog) {
	data, _ := json.MarshalIndent(changes, "", "  ")
	_ = os.WriteFile(path, data, 0644)
}

func safeJoin(baseDir, name string) (string, error) {
	joined := filepath.Join(baseDir, name)

	// 相对路径以 ".." 开头（含单独的 ".."）即说明越出了 baseDir
	rel, err := filepath.Rel(baseDir, joined)
	if err != nil {
		return "", fmt.Errorf("路径解析失败: %w", err)
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", errors.New("非法路径：路径超出目标目录")
	}

	return joined, nil
}

func copyFile(src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	_ = os.Remove(dst)
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Chmod(mode)
}

func hashFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := xxh3.New128()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	sum := h.Sum128()
	return fmt.Sprintf("%016x%016x", sum.Hi, sum.Lo), nil
}

func outputJSON(v any) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}

func fail(format string, v ...any) {
	msg := fmt.Sprintf(format, v...)
	log.Printf("错误：%s", msg)
	outputJSON(UpdateResult{Status: "failed", Message: msg})
	os.Exit(exitCodeError)
}
