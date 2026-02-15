// compare.rs — fair file/directory comparison competitor for benchmarks.
//
// Usage:
//   compare file_a file_b          — compare two files
//   compare -dir dir_a dir_b       — compare two directories recursively
//
// Exit codes: 0 = equal, 1 = different, 2 = error
//
// Uses 64KB read buffers (same as komparu default) with std::fs::File.
// No mmap — represents typical Rust I/O patterns.

use std::collections::BTreeSet;
use std::env;
use std::fs::{self, File};
use std::io::Read;
use std::path::Path;
use std::process;

const CHUNK_SIZE: usize = 65536; // 64KB — same as komparu default

fn compare_files(path_a: &str, path_b: &str) -> i32 {
    let mut fa = match File::open(path_a) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error: {}: {}", path_a, e);
            return 2;
        }
    };
    let mut fb = match File::open(path_b) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error: {}: {}", path_b, e);
            return 2;
        }
    };

    // Size precheck
    let size_a = match fa.metadata() {
        Ok(m) => m.len(),
        Err(e) => {
            eprintln!("error: {}: {}", path_a, e);
            return 2;
        }
    };
    let size_b = match fb.metadata() {
        Ok(m) => m.len(),
        Err(e) => {
            eprintln!("error: {}: {}", path_b, e);
            return 2;
        }
    };
    if size_a != size_b {
        return 1;
    }

    let mut buf_a = vec![0u8; CHUNK_SIZE];
    let mut buf_b = vec![0u8; CHUNK_SIZE];

    loop {
        let na = match fa.read(&mut buf_a) {
            Ok(n) => n,
            Err(e) => {
                eprintln!("error reading {}: {}", path_a, e);
                return 2;
            }
        };
        let nb = match fb.read(&mut buf_b) {
            Ok(n) => n,
            Err(e) => {
                eprintln!("error reading {}: {}", path_b, e);
                return 2;
            }
        };

        if na != nb || buf_a[..na] != buf_b[..nb] {
            return 1;
        }

        if na == 0 {
            return 0;
        }
    }
}

fn list_files(root: &Path) -> Result<BTreeSet<String>, std::io::Error> {
    let mut files = BTreeSet::new();
    list_files_recursive(root, root, &mut files)?;
    Ok(files)
}

fn list_files_recursive(
    root: &Path,
    dir: &Path,
    files: &mut BTreeSet<String>,
) -> Result<(), std::io::Error> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            list_files_recursive(root, &path, files)?;
        } else {
            let rel = path.strip_prefix(root).unwrap();
            files.insert(rel.to_string_lossy().into_owned());
        }
    }
    Ok(())
}

fn compare_dirs(dir_a: &str, dir_b: &str) -> i32 {
    let root_a = Path::new(dir_a);
    let root_b = Path::new(dir_b);

    let files_a = match list_files(root_a) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error listing {}: {}", dir_a, e);
            return 2;
        }
    };
    let files_b = match list_files(root_b) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("error listing {}: {}", dir_b, e);
            return 2;
        }
    };

    let all_files: BTreeSet<&String> = files_a.iter().chain(files_b.iter()).collect();

    let mut equal = true;
    for rel in &all_files {
        let in_a = files_a.contains(*rel);
        let in_b = files_b.contains(*rel);
        if !in_a || !in_b {
            equal = false;
            continue;
        }
        let pa = root_a.join(rel);
        let pb = root_b.join(rel);
        let rc = compare_files(pa.to_str().unwrap(), pb.to_str().unwrap());
        if rc == 2 {
            return 2;
        }
        if rc != 0 {
            equal = false;
        }
    }

    if equal { 0 } else { 1 }
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    let code = if args.len() == 3 && args[0] == "-dir" {
        compare_dirs(&args[1], &args[2])
    } else if args.len() == 2 {
        compare_files(&args[0], &args[1])
    } else {
        eprintln!("usage: compare [-dir] path_a path_b");
        2
    };

    process::exit(code);
}
