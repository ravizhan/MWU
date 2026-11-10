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
	"path"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/mholt/archives"
)

const (
	exitCodeSelfUpdate = 10
	exitCodeError      = 1
	extractDirName     = "update_temp"
)

type Config struct {
	Archive    string
	Kind       string
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
	exePath, err := os.Executable()
	if err != nil {
		fail("Failed to locate updater: %v", err)
	}

	// 上次更新中途崩溃留下的备份先放回去，保证从完整的旧安装开始
	restoreBackup(installDir)

	extractDir := filepath.Join(installDir, extractDirName)
	_ = os.RemoveAll(extractDir)
	if err := os.MkdirAll(extractDir, 0o755); err != nil {
		fail("Failed to create temp dir: %v", err)
	}

	log.Printf("正在将 %s 解压到 %s", cfg.Archive, extractDir)
	if err := extractArchive(ctx, cfg.Archive, extractDir); err != nil {
		fail("Failed to extract archive: %v", err)
	}

	log.Println("检查自更新...")
	if performedSelfUpdate, err := handleSelfUpdate(exePath, extractDir); err != nil {
		fail("Self update failed: %v", err)
	} else if performedSelfUpdate {
		log.Println("已执行自更新。以代码 10 退出。")
		os.RemoveAll(extractDir)
		os.Exit(exitCodeSelfUpdate)
	}

	skip := map[string]bool{
		filepath.Base(exePath): true,
		"updater.log":          true,
	}
	plan, err := buildPlan(cfg.Kind, installDir, extractDir, skip)
	if err != nil {
		fail("Failed to plan update: %v", err)
	}
	log.Printf("更新计划（%s）：替换 %d 个文件，删除 %d 个文件、%d 个目录",
		cfg.Kind, len(plan.Copy), len(plan.Delete), len(plan.DeleteDirs))

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

	log.Println("应用更新...")
	tx := newTransaction(installDir)
	if err := tx.apply(plan, extractDir); err != nil {
		log.Printf("应用失败，回滚：%v", err)
		tx.rollback()
		os.RemoveAll(extractDir)
		restartAfterFailure(cfg.RestartCmd)
		fail("Failed to apply update: %v", err)
	}
	if err := tx.commit(); err != nil {
		log.Printf("警告：清理备份失败：%v", err)
	}

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
	flag.StringVar(&cfg.Kind, "type", "full", "更新包类型：full / resource / incremental")
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
		pathInArchive := strings.ReplaceAll(f.NameInArchive, "\\", "/")
		if path.Clean(pathInArchive) == "." {
			return nil
		}

		outPath, err := safeJoin(destDir, pathInArchive)
		if err != nil {
			return fmt.Errorf("%s：%w", pathInArchive, err)
		}
		if f.IsDir() {
			return os.MkdirAll(outPath, 0o755)
		}

		if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
			return err
		}

		outFile, err := os.OpenFile(outPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, f.Mode().Perm()|0o200)
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

// handleSelfUpdate 在包内带有不同的更新器时替换自身。新更新器会被后端以退出码 10 为信号重新拉起。
func handleSelfUpdate(exePath, extractDir string) (bool, error) {
	candidate := filepath.Join(extractDir, filepath.Base(exePath))
	if _, err := os.Stat(candidate); err != nil {
		return false, nil
	}
	same, err := sameContent(exePath, candidate)
	if err != nil {
		return false, err
	}
	if same {
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

// restartAfterFailure 在回滚后拉起旧版主程序，主程序此时已被通知退出。
func restartAfterFailure(cmdStr string) {
	if err := restartMain(cmdStr); err != nil {
		log.Printf("回滚后重启主程序失败：%v", err)
	}
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
