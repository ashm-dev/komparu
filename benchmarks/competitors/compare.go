// compare.go — fair file/directory comparison competitor for benchmarks.
//
// Usage:
//   compare file_a file_b          — compare two files
//   compare -dir dir_a dir_b       — compare two directories recursively
//
// Exit codes: 0 = equal, 1 = different, 2 = error
//
// Uses 64KB read buffers (same as komparu default) with os.File.Read.
// No mmap — represents typical Go I/O patterns.

package main

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
)

const chunkSize = 65536 // 64KB — same as komparu default

func compareFiles(pathA, pathB string) int {
	fa, err := os.Open(pathA)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	defer fa.Close()

	fb, err := os.Open(pathB)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	defer fb.Close()

	// Size precheck
	infoA, err := fa.Stat()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	infoB, err := fb.Stat()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 2
	}
	if infoA.Size() != infoB.Size() {
		return 1
	}

	bufA := make([]byte, chunkSize)
	bufB := make([]byte, chunkSize)

	for {
		nA, errA := fa.Read(bufA)
		nB, errB := fb.Read(bufB)

		if nA != nB || !bytes.Equal(bufA[:nA], bufB[:nB]) {
			return 1
		}

		if errA != nil || errB != nil {
			// Both EOF = equal
			if errA == errB {
				return 0
			}
			// One EOF before the other
			return 1
		}
	}
}

func listFiles(root string) (map[string]struct{}, error) {
	files := make(map[string]struct{})
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() {
			rel, _ := filepath.Rel(root, path)
			files[rel] = struct{}{}
		}
		return nil
	})
	return files, err
}

func compareDirs(dirA, dirB string) int {
	filesA, err := listFiles(dirA)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error listing %s: %v\n", dirA, err)
		return 2
	}
	filesB, err := listFiles(dirB)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error listing %s: %v\n", dirB, err)
		return 2
	}

	// Collect all unique relative paths
	allFiles := make(map[string]struct{})
	for k := range filesA {
		allFiles[k] = struct{}{}
	}
	for k := range filesB {
		allFiles[k] = struct{}{}
	}

	sorted := make([]string, 0, len(allFiles))
	for k := range allFiles {
		sorted = append(sorted, k)
	}
	sort.Strings(sorted)

	equal := true
	for _, rel := range sorted {
		_, inA := filesA[rel]
		_, inB := filesB[rel]
		if !inA || !inB {
			equal = false
			continue
		}
		rc := compareFiles(filepath.Join(dirA, rel), filepath.Join(dirB, rel))
		if rc == 2 {
			return 2
		}
		if rc != 0 {
			equal = false
		}
	}

	if equal {
		return 0
	}
	return 1
}

func main() {
	args := os.Args[1:]
	if len(args) == 3 && args[0] == "-dir" {
		os.Exit(compareDirs(args[1], args[2]))
	} else if len(args) == 2 {
		os.Exit(compareFiles(args[0], args[1]))
	} else {
		fmt.Fprintf(os.Stderr, "usage: compare [-dir] path_a path_b\n")
		os.Exit(2)
	}
}
