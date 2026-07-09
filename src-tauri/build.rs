use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn main() {
    println!("cargo:rerun-if-changed=binaries/ms-playwright");

    let cargo_manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let source_dir = Path::new(&cargo_manifest_dir)
        .join("binaries")
        .join("ms-playwright");

    if !source_dir.exists() {
        println!("cargo:warning=Playwright browser folder missing src-tauri/binaries/ms-playwright, make sure it's installed by setting the PLAYWRIGHT_BROWSER_PATH env before running playwright install chromium command");
        tauri_build::build();
        return;
    }

    let out_dir = env::var("OUT_DIR").unwrap();
    let target_dir = find_target_dir(&Path::new(&out_dir));

    if let Some(target) = target_dir {
        let destination_dir = target.join("binaries").join("ms-playwright");

        if destination_dir.exists() {
            let _ = fs::remove_dir_all(&destination_dir);
        }

        copy_dir_all(&source_dir, &destination_dir)
            .expect("Failed to copy playwright browsers to the target folder");
    }

    tauri_build::build()
}

// Helper to crawl backward from OUT_DIR until reaching the target profile path
fn find_target_dir(out_dir: &Path) -> Option<PathBuf> {
    let mut current = out_dir;
    while let Some(parent) = current.parent() {
        if parent.file_name()?.to_str()? == "target" {
            return Some(current.to_path_buf());
        }
        current = parent
    }
    None
}

// Deep recursive copier that explicitly separates directories from files
fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    // 1. Ensure the target directory path exists
    fs::create_dir_all(dst)?;

    // 2. Iterate through the target directory entries
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let path = entry.path();
        let file_name = entry.file_name();
        let destination_path = dst.join(file_name);

        // 3. Check what the file layout is before acting on it
        if path.is_dir() {
            // Recurse into subdirectories safely
            copy_dir_all(&path, &destination_path)?;
        } else {
            // It's a regular file or symlink, safe to copy using standard std::fs::copy
            fs::copy(&path, &destination_path)?;
        }
    }
    Ok(())
}
