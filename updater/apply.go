package main

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/zeebo/xxh3"
)

const backupDirName = "update_backup"

// Plan 是一次更新要做的文件操作，路径均相对安装目录。
type Plan struct {
	Copy       []string // 从解压目录放到安装目录
	Delete     []string // 从安装目录删除
	DeleteDirs []string // 文件处理完后删除的目录（含其中剩余内容）
	Manifest   *Manifest
}

// buildPlan 按包类型决定替换与删除范围：
//   - full：包内文件全部生效；旧清单里有、新清单里没有的文件删除。没有旧清单（旧安装或首次）时不删除。
//   - resource：只含资源文件，要求本地与包内清单的 MWU 版本一致，删除旧清单中多余的资源文件。
//   - incremental：MirrorChyan 增量包，严格按 changes.json 执行。
func buildPlan(kind, installDir, extractDir string, skip map[string]bool) (Plan, error) {
	var newManifest Manifest
	hasNew, err := readJSON(filepath.Join(extractDir, manifestFile), &newManifest)
	if err != nil {
		return Plan{}, err
	}
	var oldManifest Manifest
	hasOld, err := readJSON(filepath.Join(installDir, manifestFile), &oldManifest)
	if err != nil {
		return Plan{}, err
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
		plan.Copy = append(slices.Clone(changes.Added), changes.Modified...)
		plan.Delete = changes.Deleted
		plan.DeleteDirs = changes.DeletedDir
		for _, rel := range changes.AddedDir {
			if err := mkdirIn(installDir, rel); err != nil {
				return Plan{}, err
			}
		}
	case "resource":
		if !hasNew || !hasOld {
			return Plan{}, errors.New("资源包更新需要本地与包内都有安装清单，请改用完整包")
		}
		if newManifest.MWUVersion != oldManifest.MWUVersion {
			return Plan{}, fmt.Errorf("资源包要求 MWU %s，本地为 %s，请改用完整包",
				newManifest.MWUVersion, oldManifest.MWUVersion)
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
			plan.Delete = removedFiles(append(slices.Clone(oldManifest.Client), oldManifest.Resource...), newManifest.files())
		}
	default:
		return Plan{}, fmt.Errorf("未知的更新包类型：%s", kind)
	}

	// 清单最后单独写入：中途失败时本地清单仍描述旧安装
	plan.Copy = slices.DeleteFunc(plan.Copy, func(rel string) bool {
		return skip[rel] || rel == manifestFile || rel == changesFile
	})
	changed, err := changedFiles(installDir, extractDir, plan.Copy)
	if err != nil {
		return Plan{}, err
	}
	plan.Copy = changed
	plan.Delete = slices.DeleteFunc(plan.Delete, func(rel string) bool { return skip[rel] })
	for _, rel := range slices.Concat(plan.Copy, plan.Delete, plan.DeleteDirs) {
		if _, err := safeJoin(installDir, rel); err != nil {
			return Plan{}, fmt.Errorf("%s：%w", rel, err)
		}
	}
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
func changedFiles(installDir, extractDir string, rels []string) ([]string, error) {
	var changed []string
	for _, rel := range rels {
		src := filepath.Join(extractDir, rel)
		srcInfo, err := os.Stat(src)
		if err != nil {
			return nil, fmt.Errorf("包内缺少文件 %s：%w", rel, err)
		}
		dstInfo, err := os.Stat(filepath.Join(installDir, rel))
		if err != nil || dstInfo.Size() != srcInfo.Size() {
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

// Transaction 记录已做的改动，失败时按逆序撤销。被替换或删除的文件先移入 update_backup/。
type Transaction struct {
	installDir string
	backupDir  string
	created    []string // 原本不存在、由本次更新新建的文件
	backedUp   []string // 已移入备份目录的文件
}

func newTransaction(installDir string) *Transaction {
	return &Transaction{installDir: installDir, backupDir: filepath.Join(installDir, backupDirName)}
}

func (t *Transaction) backup(rel string) (bool, error) {
	dst := filepath.Join(t.installDir, rel)
	if _, err := os.Lstat(dst); errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	saved := filepath.Join(t.backupDir, rel)
	if err := os.MkdirAll(filepath.Dir(saved), 0o755); err != nil {
		return false, err
	}
	if err := os.Rename(dst, saved); err != nil {
		return false, err
	}
	t.backedUp = append(t.backedUp, rel)
	return true, nil
}

func (t *Transaction) put(extractDir, rel string) error {
	existed, err := t.backup(rel)
	if err != nil {
		return err
	}
	dst := filepath.Join(t.installDir, rel)
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	if !existed {
		t.created = append(t.created, rel)
	}
	return os.Rename(filepath.Join(extractDir, rel), dst)
}

func (t *Transaction) remove(rel string) error {
	_, err := t.backup(rel)
	return err
}

func (t *Transaction) removeDir(rel string) error {
	dir := filepath.Join(t.installDir, rel)
	files, err := listFiles(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, f := range files {
		if err := t.remove(filepath.ToSlash(filepath.Join(rel, f))); err != nil {
			return err
		}
	}
	return os.RemoveAll(dir)
}

func (t *Transaction) apply(plan Plan, extractDir string) error {
	for _, rel := range plan.Copy {
		if err := t.put(extractDir, rel); err != nil {
			return fmt.Errorf("替换 %s 失败：%w", rel, err)
		}
	}
	for _, rel := range plan.Delete {
		if err := t.remove(rel); err != nil {
			return fmt.Errorf("删除 %s 失败：%w", rel, err)
		}
	}
	for _, rel := range plan.DeleteDirs {
		if err := t.removeDir(rel); err != nil {
			return fmt.Errorf("删除目录 %s 失败：%w", rel, err)
		}
	}
	if plan.Manifest != nil {
		if err := t.put(extractDir, manifestFile); err != nil {
			return fmt.Errorf("写入安装清单失败：%w", err)
		}
	}
	return nil
}

func (t *Transaction) rollback() {
	for _, rel := range slices.Backward(t.created) {
		if err := os.Remove(filepath.Join(t.installDir, rel)); err != nil && !errors.Is(err, fs.ErrNotExist) {
			log.Printf("回滚：删除 %s 失败：%v", rel, err)
		}
	}
	t.created = nil
	restoreBackup(t.installDir)
}

func (t *Transaction) commit() error {
	return os.RemoveAll(t.backupDir)
}

// restoreBackup 把备份目录中的文件放回原处。更新中途崩溃后，下次运行更新器会先调用它恢复旧安装。
func restoreBackup(installDir string) {
	backupDir := filepath.Join(installDir, backupDirName)
	files, err := listFiles(backupDir)
	if errors.Is(err, fs.ErrNotExist) {
		return
	}
	if err != nil {
		log.Printf("读取备份目录失败：%v", err)
		return
	}
	for _, rel := range files {
		dst := filepath.Join(installDir, rel)
		_ = os.MkdirAll(filepath.Dir(dst), 0o755)
		_ = os.Remove(dst)
		if err := os.Rename(filepath.Join(backupDir, rel), dst); err != nil {
			log.Printf("恢复 %s 失败：%v", rel, err)
			return
		}
	}
	if err := os.RemoveAll(backupDir); err != nil {
		log.Printf("清理备份目录失败：%v", err)
	}
}

func mkdirIn(baseDir, rel string) error {
	dir, err := safeJoin(baseDir, rel)
	if err != nil {
		return fmt.Errorf("%s：%w", rel, err)
	}
	return os.MkdirAll(dir, 0o755)
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
