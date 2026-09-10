# Creating a GitHub Release

The connected tools used while developing this repo cannot always publish a GitHub Release UI entry automatically. Use one of these methods:

## Method A — Tag + GitHub Actions (recommended)

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow `.github/workflows/release.yml` builds `SC2ChatBot-portable-v1.0.0.zip` (Simulated + OCR launchers in **one** zip) and publishes a Release.

You can also run the workflow manually: **Actions → Release portable package → Run workflow**.

## Method B — Upload manually

1. Build or download the portable zip (includes both modes).
2. GitHub → **Releases** → **Draft a new release**
3. Tag: `v1.0.0`
4. Attach `SC2ChatBot-portable-v1.0.0.zip`
5. Publish

## What’s in the zip

- Full bot source (both backends)
- `RUN_SIMULATED.bat` / `run_simulated.sh`
- `RUN_OCR.bat` / `run_ocr.sh`
- `config/config.yaml` (switch `chat_backend`)
- `tools/measure_chat_region.py`
- Build scripts for optional PyInstaller exe later
