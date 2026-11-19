# SPDX-License-Identifier: GPL-3.0-or-later
"""HueAtlas headless test runner.

Usage (from the repository root):

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/run_all.py -- [--lite] [--only NAME] [--junit out.xml]
        [--installed path/to/hueatlas.zip] [--update-golden]

--lite        run with the lite edition's restrictions (paid package not registered)
--installed   install the built extension zip and test that instead of src/
"""

import importlib
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _arg(name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


if "--lite" in argv:
    os.environ["HUEATLAS_FORCE_LITE"] = "1"
if "--update-golden" in argv:
    os.environ["HUEATLAS_UPDATE_GOLDEN"] = "1"

import bpy  # noqa: E402

installed_zip = _arg("--installed")
if installed_zip:
    bpy.ops.extensions.package_install_files(
        filepath=os.path.abspath(installed_zip), repo="user_default", enable_on_install=True
    )
    prefix = None
    for name in list(sys.modules):
        if name.startswith("bl_ext.") and name.endswith((".hueatlas", ".hueatlas_lite")):
            prefix = name
    if prefix is None:
        raise SystemExit("Installed extension not found in sys.modules")
    for name, mod in list(sys.modules.items()):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules["hueatlas" + name[len(prefix):]] = mod
    print(f"Testing installed package {prefix}")
else:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import hueatlas  # noqa: E402

    hueatlas.register()

sys.path.insert(0, HERE)
from hueatlas import edition  # noqa: E402

only = _arg("--only")
results = []
started = time.perf_counter()

for fname in sorted(os.listdir(HERE)):
    if not (fname.startswith("test_") and fname.endswith(".py")):
        continue
    mod = importlib.import_module(fname[:-3])
    for name, fn in list(vars(mod).items()):
        if not (name.startswith("test_") and callable(fn)):
            continue
        full = f"{fname[:-3]}.{name}"
        if only and only not in full:
            continue
        if getattr(fn, "paid_only", False) and not edition.PAID:
            results.append((full, "skip", 0.0, "full version only"))
            continue
        if getattr(fn, "lite_only", False) and edition.PAID:
            results.append((full, "skip", 0.0, "lite only"))
            continue
        t0 = time.perf_counter()
        try:
            fn()
            results.append((full, "pass", time.perf_counter() - t0, ""))
        except Exception:
            results.append((full, "FAIL", time.perf_counter() - t0, traceback.format_exc()))

print()
print(f"HueAtlas tests: edition={edition.EDITION} blender={bpy.app.version_string}")
for full, status, secs, info in results:
    print(f"  [{status:>4}] {full} ({secs:.2f}s)")
    if status == "FAIL":
        print("        " + info.replace("\n", "\n        "))
fails = [r for r in results if r[1] == "FAIL"]
passes = [r for r in results if r[1] == "pass"]
skips = [r for r in results if r[1] == "skip"]
print(f"{len(passes)} passed, {len(fails)} failed, {len(skips)} skipped in {time.perf_counter() - started:.1f}s")

junit = _arg("--junit")
if junit:
    from xml.sax.saxutils import escape

    with open(junit, "w", encoding="utf-8") as fh:
        fh.write(f'<testsuite name="hueatlas-{edition.EDITION}" tests="{len(results)}" failures="{len(fails)}">\n')
        for full, status, secs, info in results:
            fh.write(f'  <testcase name="{escape(full)}" time="{secs:.3f}">')
            if status == "FAIL":
                fh.write(f"<failure>{escape(info)}</failure>")
            elif status == "skip":
                fh.write(f'<skipped message="{escape(info)}"/>')
            fh.write("</testcase>\n")
        fh.write("</testsuite>\n")

if fails:
    raise SystemExit(1)
