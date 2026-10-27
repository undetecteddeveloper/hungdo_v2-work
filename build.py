"""Build Hứng Đồ v2 into a single-file exe with PyInstaller.

Usage: python build.py [--no-test]
Output: dist/HungDo_v2.exe (dist/ and build/ are git-ignored).
Runs the exe once with --autoplay --smoke-seconds 5 unless --no-test is given.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "HungDo_v2"
SEP = os.pathsep  # PyInstaller --add-data separator: ';' on Windows, ':' elsewhere


def build() -> str:
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", os.path.join(ROOT, "assets", "icon.ico"),
        "--add-data", f"{os.path.join(ROOT, 'assets')}{SEP}assets",
        "--add-data", f"{os.path.join(ROOT, 'lang')}{SEP}lang",
        "--paths", ROOT,
        "--hidden-import", "numpy",
        # scene modules are imported by name at runtime (see app.py), so list them explicitly
        "--collect-submodules", "game",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "main.py"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = os.path.join(ROOT, "dist", NAME + (".exe" if os.name == "nt" else ""))
    if not os.path.isfile(exe):
        raise SystemExit(f"build finished but {exe} is missing")
    return exe


def self_test(exe: str) -> None:
    import tempfile
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    with tempfile.TemporaryDirectory() as data_dir:
        r = subprocess.run([exe, "--autoplay", "--smoke-seconds", "5", "--data-dir", data_dir],
                           env=env, timeout=60)
    if r.returncode != 0:
        raise SystemExit(f"exe self-test failed with exit code {r.returncode}")
    print("exe self-test OK")


if __name__ == "__main__":
    path = build()
    print(f"built {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    if "--no-test" not in sys.argv:
        self_test(path)
