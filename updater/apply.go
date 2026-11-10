package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"

	"github.com/zeebo/xxh3"
)

const (
	backupDirName   = "update_backup"
	backupFilesDir  = "files"        // 被替换或删除的旧文件，按原相对路径存放
	createdListFile = "created.json" // 本次更新新建的路径，还原时删除
	committedFile   = "committed"    // 存在即更新已完成，备份只需清理
)

// Plan 是一次更新要做的文件操作，路径均相对安装目录。
type Plan struct {
	Copy      []string // 从解压目录放到安装目录
	Delete    []string // 从安装目录删除
	MakeDirs  []string // 需要创建的目录（增量包 added_dir）
	PruneDirs []string // 删除文件后若已为空则移除的目录（增量包 deleted_dir）
	Manifest  *Manifest
}

// buildPlan 按包类型决定替换与删除范围：
//   - full：包内文件全部生效；旧清单里有、新清单里没有的文件删除。没有可用的旧清单（旧安装或首次）时不删除。
//   - resource：只含资源文件，要求本地与包内清单的 MWU 版本一致、本地没有覆盖本体的资源，删除旧清单中多余的资源文件。
//   - incremental：MirrorChyan 增量包，按 changes.json 执行；删除目录时只移除其中已清空的目录。
func buildPlan(kind, installDir, extractDir string, skip map[string]bool) (Plan, error) {
	var newManifest Manifest
	hasNew, err := readJSON(filepath.Join(extractDir, manifestFile), &newManifest)
	if err != nil {
		return Plan{}, err
	}
	var oldManifest Manifest
	hasOld, err := readJSON(filepath.Join(installDir, manifestFile), &oldManifest)
	if err != nil {
		// 本地清单损坏时按没有清单处理：完整包照常覆盖，只是不删除旧文件
		log.Printf("忽略无法读取的本地安装清单：%v", err)
		hasOld = false
	}

	var plan Plan
	if hasNew {
		plan.Manifest = &newManifest
	}

	switch kind {
	case "incremental":
		var changes ChangeLog
		found, err := readJSON(filepath.Join(extractDir, changesFile), &changes)
		if err != nil {
			return Plan{}, err
		}
		if !found {
			return Plan{}, errors.New("增量包缺少 changes.json")
		}
		plan.Copy = slices.Concat(changes.Added, changes.Modified)
		plan.Delete = changes.Deleted
		plan.MakeDirs = changes.AddedDir
		plan.PruneDirs = changes.DeletedDir
	case "resource":
		if !hasNew || !hasOld {
			return Plan{}, errors.New("资源包更新需要本地与包内都有安装清单，请改用完整包")
		}
		if newManifest.MWUVersion != oldManifest.MWUVersion {
			return Plan{}, fmt.Errorf("资源包要求 MWU %s，本地为 %s，请改用完整包",
				newManifest.MWUVersion, oldManifest.MWUVersion)
		}
		if oldManifest.overridesClient() {
			return Plan{}, errors.New("本地有覆盖 MWU 本体文件的资源，资源包无法还原这些文件，请改用完整包")
		}
		plan.Copy = newManifest.Resource
		plan.Delete = removedFiles(oldManifest.Resource, newManifest.files())
	case "full":
		files, err := listFiles(extractDir)
		if err != nil {
			return Plan{}, err
		}
		plan.Copy = files
		if hasOld && hasNew {
			plan.Delete = removedFiles(slices.Concat(oldManifest.Client, oldManifest.Resource), newManifest.files())
		}
	default:
		return Plan{}, fmt.Errorf("未知的更新包类型：%s", kind)
	}

	// 清单最后单独写入：中途失败时本地清单仍描述旧安装
	plan.Copy = slices.DeleteFunc(plan.Copy, func(rel string) bool {
		return skip[rel] || rel == manifestFile || rel == changesFile
	})
	plan.Delete = slices.DeleteFunc(plan.Delete, func(rel string) bool { return skip[rel] })
	// 先校验再访问文件，越界路径在任何读取之前被拒绝
	for _, rel := range slices.Concat(plan.Copy, plan.Delete, plan.MakeDirs, plan.PruneDirs) {
		if err := checkInstallPath(installDir, rel); err != nil {
			return Plan{}, fmt.Errorf("%s：%w", rel, err)
		}
	}
	changed, err := changedFiles(installDir, extractDir, plan.Copy)
	if err != nil {
		return Plan{}, err
	}
	plan.Copy = changed
	return plan, nil
}

func removedFiles(old []string, keep map[string]bool) []string {
	var removed []string
	for _, rel := range old {
		if !keep[rel] {
			removed = append(removed, rel)
		}
	}
	return removed
}

func listFiles(root string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		files = append(files, filepath.ToSlash(rel))
		return nil
	})
	return files, err
}

// changedFiles 去掉内容与安装目录一致的文件，避免无谓的替换与备份。
// 包内可执行而本地不可执行的文件也算变化，否则内容相同时权限无法修复。
func changedFiles(installDir, extractDir string, rels []string) ([]string, error) {
	var changed []string
	for _, rel := range rels {
		src := filepath.Join(extractDir, rel)
		srcInfo, err := os.Stat(src)
		if err != nil {
			return nil, fmt.Errorf("包内缺少文件 %s：%w", rel, err)
		}
		dstInfo, err := os.Stat(filepath.Join(installDir, rel))
		if err != nil || dstInfo.Size() != srcInfo.Size() ||
			srcInfo.Mode()&0o111 != 0 && dstInfo.Mode()&0o111 == 0 {
			changed = append(changed, rel)
			continue
		}
		same, err := sameContent(src, filepath.Join(installDir, rel))
		if err != nil {
			return nil, err
		}
		if !same {
			changed = append(changed, rel)
		}
	}
	return changed, nil
}

func sameContent(a, b string) (bool, error) {
	ha, err := hashFile(a)
	if err != nil {
		return false, err
	}
	hb, err := hashFile(b)
	if err != nil {
		return false, err
	}
	return ha == hb, nil
}

func hashFile(path string) (xxh3.Uint128, error) {
	f, err := os.Open(path)
	if err != nil {
		return xxh3.Uint128{}, err
	}
	defer f.Close()
	h := xxh3.New128()
	if _, err := io.Copy(h, f); err != nil {
		return xxh3.Uint128{}, err
	}
	return h.Sum128(), nil
}

// Transaction 让一次更新可以撤销：动文件前先把将新建的路径写入 created.json，
// 被替换或删除的旧文件移入 update_backup/files/。失败或崩溃后 restoreBackup 据此还原旧安装。
type Transaction struct {
	installDir string
	backupDir  string
}

func newTransaction(installDir string) *Transaction {
	return &Transaction{installDir: installDir, backupDir: filepath.Join(installDir, backupDirName)}
}

func (t *Transaction) apply(plan Plan, extractDir string) error {
	if err := t.begin(plan); err != nil {
		return fmt.Errorf("记录更新事务失败：%w", err)
	}
	// 先删后建：目录与同名文件互换时，旧路径先让出位置
	for _, rel := range plan.Delete {
		if err := t.backup(rel); err != nil {
			return fmt.Errorf("删除 %s 失败：%w", rel, err)
		}
	}
	for _, rel := range plan.PruneDirs {
		if err := pruneEmptyDirs(filepath.Join(t.installDir, rel)); err != nil {
			return fmt.Errorf("删除目录 %s 失败：%w", rel, err)
		}
	}
	for _, rel := range plan.MakeDirs {
		if err := os.MkdirAll(filepath.Join(t.installDir, rel), 0o755); err != nil {
			return fmt.Errorf("创建目录 %s 失败：%w", rel, err)
		}
	}
	for _, rel := range plan.Copy {
		if err := t.put(extractDir, rel); err != nil {
			return fmt.Errorf("替换 %s 失败：%w", rel, err)
		}
	}
	if plan.Manifest != nil {
		if err := t.put(extractDir, manifestFile); err != nil {
			return fmt.Errorf("写入安装清单失败：%w", err)
		}
	}
	return nil
}

// begin 在改动任何文件前持久化将被新建的路径：原本不存在的目录与文件，以及将被同名文件取代的目录。
func (t *Transaction) begin(plan Plan) error {
	targets := slices.Concat(plan.MakeDirs, plan.Copy)
	if plan.Manifest != nil {
		targets = append(targets, manifestFile)
	}
	created := []string{}
	for i, rel := range targets {
		info, err := os.Lstat(filepath.Join(t.installDir, rel))
		// 已存在的目录：MakeDirs 中的保持原样；Copy 中的会被同名文件取代，需要记录
		if isMissing(err) || err == nil && info.IsDir() && i >= len(plan.MakeDirs) {
			created = append(created, rel)
			continue
		}
		if err != nil {
			return err
		}
	}
	if err := os.MkdirAll(filepath.Join(t.backupDir, backupFilesDir), 0o755); err != nil {
		return err
	}
	data, err := json.Marshal(created)
	if err != nil {
		return err
	}
	return writeFileSync(filepath.Join(t.backupDir, createdListFile), data)
}

func (t *Transaction) backup(rel string) error {
	src := filepath.Join(t.installDir, rel)
	if _, err := os.Lstat(src); errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	saved := filepath.Join(t.backupDir, backupFilesDir, rel)
	if err := os.MkdirAll(filepath.Dir(saved), 0o755); err != nil {
		return err
	}
	return os.Rename(src, saved)
}

func (t *Transaction) put(extractDir, rel string) error {
	dst := filepath.Join(t.installDir, rel)
	info, err := os.Lstat(dst)
	switch {
	case err == nil && info.IsDir():
		// 目录换成同名文件：目录里的旧文件已按计划删除，剩下的空目录让位；仍有其他文件则后续改名失败并回滚
		if err := pruneEmptyDirs(dst); err != nil {
			return err
		}
	case err == nil:
		if err := t.backup(rel); err != nil {
			return err
		}
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	return os.Rename(filepath.Join(extractDir, rel), dst)
}

func (t *Transaction) rollback() error {
	return restoreBackup(t.installDir)
}

// commit 只写完成标记；之后 discardBackup 清理备份。清理中途失败时标记仍在，
// 下次运行只会继续清理，不会把旧文件恢复到已完成的安装上。
func (t *Transaction) commit() error {
	return writeFileSync(filepath.Join(t.backupDir, committedFile), nil)
}

// discardBackup 删除备份目录，完成标记最后删除。
func discardBackup(backupDir string) error {
	if err := os.RemoveAll(filepath.Join(backupDir, backupFilesDir)); err != nil {
		return err
	}
	if err := os.Remove(filepath.Join(backupDir, createdListFile)); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return os.RemoveAll(backupDir)
}

// recoverBackup 处理上次运行留下的备份：已提交的只清理，未提交的（更新中途崩溃）还原旧安装。
func recoverBackup(installDir string) error {
	backupDir := filepath.Join(installDir, backupDirName)
	if _, err := os.Stat(backupDir); errors.Is(err, fs.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	if _, err := os.Stat(filepath.Join(backupDir, committedFile)); err == nil {
		return discardBackup(backupDir)
	}
	log.Println("发现未完成的更新，正在还原旧安装...")
	return restoreBackup(installDir)
}

// restoreBackup 撤销未提交的更新：逆序删除本次新建的文件和已清空的新目录，把备份的旧文件放回原处，最后移除备份目录。
// 可重复执行：中途失败后再次调用会从剩余状态继续。
func restoreBackup(installDir string) error {
	backupDir := filepath.Join(installDir, backupDirName)
	if _, err := os.Stat(backupDir); errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	var created []string
	if _, err := readJSON(filepath.Join(backupDir, createdListFile), &created); err != nil {
		return err
	}
	for _, rel := range slices.Backward(created) {
		path := filepath.Join(installDir, rel)
		info, err := os.Lstat(path)
		if isMissing(err) {
			continue
		}
		if err != nil {
			return err
		}
		if info.IsDir() {
			if err := pruneEmptyDirs(path); err != nil {
				return fmt.Errorf("删除新目录 %s 失败：%w", rel, err)
			}
			continue
		}
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("删除新文件 %s 失败：%w", rel, err)
		}
	}
	filesDir := filepath.Join(backupDir, backupFilesDir)
	files, err := listFiles(filesDir)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("读取备份目录失败：%w", err)
	}
	for _, rel := range files {
		dst := filepath.Join(installDir, rel)
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return fmt.Errorf("恢复 %s 失败：%w", rel, err)
		}
		if err := os.Remove(dst); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return fmt.Errorf("恢复 %s 失败：%w", rel, err)
		}
		if err := os.Rename(filepath.Join(filesDir, rel), dst); err != nil {
			return fmt.Errorf("恢复 %s 失败：%w", rel, err)
		}
	}
	return os.RemoveAll(backupDir)
}

// pruneEmptyDirs 自底向上移除 dir 下（含 dir）已为空的目录。仍有文件的目录保留：
// 增量包删除目录时，目录里不属于发布的文件（用户数据）不受影响。
func pruneEmptyDirs(dir string) error {
	var dirs []string
	err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err == nil && d.IsDir() {
			dirs = append(dirs, path)
		}
		return err
	})
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, d := range slices.Backward(dirs) {
		entries, err := os.ReadDir(d)
		if err != nil {
			return err
		}
		if len(entries) > 0 {
			continue
		}
		if err := os.Remove(d); err != nil {
			return err
		}
	}
	if _, err := os.Lstat(dir); err == nil {
		log.Printf("目录 %s 中仍有不属于发布的文件，已保留", dir)
	}
	return nil
}

// writeFileSync 原子写入并落盘：先写临时文件再替换，中途崩溃不会留下半截内容。
func writeFileSync(path string, data []byte) error {
	tmp := path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// isMissing 判断路径不存在；Unix 上父路径是文件时返回 ENOTDIR，同样视为不存在。
func isMissing(err error) bool {
	return errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ENOTDIR)
}

// checkInstallPath 拒绝越界路径，以及经过链接或挂载点的路径：更新只能改动安装目录内的真实文件。
func checkInstallPath(installDir, rel string) error {
	if _, err := safeJoin(installDir, rel); err != nil {
		return err
	}
	dir := installDir
	parts := strings.Split(filepath.Clean(filepath.FromSlash(rel)), string(filepath.Separator))
	for _, part := range parts[:len(parts)-1] {
		dir = filepath.Join(dir, part)
		info, err := os.Lstat(dir)
		if isMissing(err) {
			return nil
		}
		if err != nil {
			return err
		}
		if info.Mode()&(fs.ModeSymlink|fs.ModeIrregular) != 0 {
			return errors.New("非法路径：经过符号链接或挂载点")
		}
	}
	return nil
}

func safeJoin(baseDir, name string) (string, error) {
	if filepath.IsAbs(name) || filepath.VolumeName(name) != "" || strings.HasPrefix(name, `\\`) {
		return "", errors.New("非法路径：不允许绝对路径")
	}
	joined := filepath.Join(baseDir, name)
	rel, err := filepath.Rel(baseDir, joined)
	if err != nil {
		return "", fmt.Errorf("路径解析失败：%w", err)
	}
	if rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", errors.New("非法路径：路径超出目标目录")
	}
	return joined, nil
}
