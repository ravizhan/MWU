package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
)

const (
	manifestFile = "mwu-install.json"
	changesFile  = "changes.json"
)

// Manifest 描述一次安装由哪些文件组成：client 来自 MWU 发布包，resource 由资源项目写入。
// 路径均为相对安装目录、以 "/" 分隔。
type Manifest struct {
	Version    string   `json:"version"`
	MWUVersion string   `json:"mwu_version"`
	Client     []string `json:"client"`
	Resource   []string `json:"resource"`
}

func (m *Manifest) files() map[string]bool {
	files := make(map[string]bool, len(m.Client)+len(m.Resource))
	for _, rel := range m.Client {
		files[rel] = true
	}
	for _, rel := range m.Resource {
		files[rel] = true
	}
	return files
}

// ChangeLog 是 MirrorChyan 增量包中的 changes.json。
type ChangeLog struct {
	Added      []string `json:"added"`
	Modified   []string `json:"modified"`
	Deleted    []string `json:"deleted"`
	AddedDir   []string `json:"added_dir"`
	DeletedDir []string `json:"deleted_dir"`
}

// readJSON 读取并解析 JSON 文件；文件不存在时返回 false。
func readJSON(path string, v any) (bool, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if err := json.Unmarshal(data, v); err != nil {
		return false, fmt.Errorf("解析 %s 失败：%w", path, err)
	}
	return true, nil
}
