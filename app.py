"""
Manim Studio - Native Desktop Application
Uses PyWebView to create a native desktop window with HTML/CSS/JS UI
Single executable with PyInstaller
"""
import webview
import os
import sys
import tempfile
import subprocess
import json
import threading
import time
from pathlib import Path
import re
import socket

# App version
APP_VERSION = "1.0.5.0"

# Terminal emulation with PTY support
try:
    import winpty
    WINPTY_AVAILABLE = True
except ImportError:
    WINPTY_AVAILABLE = False
    print("[WARNING] pywinpty not available - terminal will use fallback mode")

# No AI/LLM imports - feature removed

# Determine base directory
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# User data directory (defined early for use in setup_venv)
# Force exact structure: C:\Users\<username>\.manim_studio
USER_DATA_DIR = os.path.join(os.path.expanduser('~'), '.manim_studio')
MEDIA_DIR = os.path.join(USER_DATA_DIR, 'media')  # Render output folder
ASSETS_DIR = os.path.join(USER_DATA_DIR, 'assets')
PREVIEW_DIR = os.path.join(USER_DATA_DIR, 'preview')  # Preview folder (cleared before each preview)
RENDER_DIR = os.path.join(USER_DATA_DIR, 'render')  # Render folder (for high-quality renders)
AUTOSAVE_DIR = os.path.join(USER_DATA_DIR, 'autosave')  # Auto-save directory

# Virtual environment directory - always at: ~/.manim_studio/venvs/manim_studio_default
VENV_DIR = os.path.join(USER_DATA_DIR, 'venvs', 'manim_studio_default')

# Set encoding environment variables (crucial for Windows)
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONLEGACYWINDOWSFSENCODING'] = '0'
os.environ['PYTHONUTF8'] = '1'

def get_clean_environment():
    """
    Get a clean environment for running Python subprocesses.
    This prevents the exe from accidentally being used as Python interpreter.
    Critical: Removes PYTHONPATH and PYTHONHOME to prevent circular execution.
    """
    env = os.environ.copy()

    # CRITICAL: REMOVE (not just clear) these variables to prevent exe interference
    # Setting to empty string can cause issues - we need to delete them
    keys_to_remove = ['PYTHONPATH', 'PYTHONHOME', '__PYVENV_LAUNCHER__']
    for key in keys_to_remove:
        if key in env:
            del env[key]
            print(f"[ENV] Removed {key} from environment")

    # Set encoding for proper UTF-8 handling
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONLEGACYWINDOWSFSENCODING'] = '0'
    env['PYTHONUTF8'] = '1'

    # If frozen, ensure exe directory is not interfering
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        print(f"[ENV] Running as frozen EXE from: {exe_dir}")

        # Remove exe directory from PATH if present
        if 'PATH' in env:
            path_parts = env['PATH'].split(os.pathsep)
            original_count = len(path_parts)
            path_parts = [p for p in path_parts if os.path.normpath(p) != os.path.normpath(exe_dir)]
            if len(path_parts) < original_count:
                print(f"[ENV] Removed EXE directory from PATH")
            env['PATH'] = os.pathsep.join(path_parts)

        # Ensure system Python paths are available
        # This helps the venv Python find system DLLs
        system_paths = [
            r'C:\Windows\System32',
            r'C:\Windows',
            r'C:\Windows\System32\Wbem',
            r'C:\Windows\System32\WindowsPowerShell\v1.0'
        ]

        current_paths = env.get('PATH', '').split(os.pathsep)
        for sys_path in system_paths:
            if os.path.exists(sys_path) and sys_path not in current_paths:
                current_paths.append(sys_path)

        env['PATH'] = os.pathsep.join(current_paths)
        print(f"[ENV] PATH configured with {len(current_paths)} entries")

    return env

# Function to find system Python using 'where python' command
def find_system_python():
    """
    Find Python interpreter using multiple methods:
    1. 'where python' command (PATH-based)
    2. Windows Registry (for Python installed via official installer)
    3. Common installation locations
    """
    print("\n[INFO] Searching for system Python...")

    # Get exe info to avoid using it
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        exe_path = os.path.abspath(sys.executable).lower()
        exe_dir = os.path.dirname(exe_path).lower()
        print(f"[INFO] Running as exe: {exe_path}")
        print(f"[INFO] Will reject any Python in: {exe_dir}")
    else:
        exe_path = None
        exe_dir = None
        print("[INFO] Running as Python script")

    def is_valid_python(python_path):
        """Check if a Python path is valid and not the exe itself"""
        if not os.path.exists(python_path):
            return False

        abs_path = os.path.abspath(python_path).lower()
        dirname = os.path.dirname(abs_path)
        basename = os.path.basename(abs_path)

        # Skip if it's the exe itself or in exe directory
        if is_frozen:
            if abs_path == exe_path:
                print(f"  [SKIP] This is the exe itself: {python_path}")
                return False
            if dirname == exe_dir:
                print(f"  [SKIP] In exe directory: {python_path}")
                return False

        # Skip if in BASE_DIR
        if dirname == os.path.normpath(BASE_DIR).lower():
            print(f"  [SKIP] In BASE_DIR: {python_path}")
            return False

        # Skip if filename contains "manim" or "studio"
        if 'manim' in basename or 'studio' in basename:
            print(f"  [SKIP] Filename contains 'manim' or 'studio': {python_path}")
            return False

        # Skip paths containing "manim" UNLESS it's our venv
        if 'manim' in abs_path:
            venv_normalized = os.path.normpath(VENV_DIR).lower()
            if not abs_path.startswith(venv_normalized):
                print(f"  [SKIP] Path contains 'manim' (not our venv): {python_path}")
                return False

        # Verify it works
        try:
            env = get_clean_environment()
            test_result = subprocess.run(
                [python_path, '--version'],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            version = (test_result.stdout + test_result.stderr).strip()
            if 'python' in version.lower():
                print(f"  [SUCCESS] Valid Python: {version}")
                return True
            else:
                print(f"  [SKIP] Not Python: {version}")
                return False
        except Exception as e:
            print(f"  [SKIP] Version check failed: {e}")
            return False

    # Method 1: Try 'where python' command (PATH-based)
    print("\n[METHOD 1] Trying 'where python' command...")
    try:
        env = get_clean_environment()
        result = subprocess.run(
            ['where', 'python'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        if result.returncode == 0:
            pythons = result.stdout.strip().split('\n')
            print(f"[INFO] Found {len(pythons)} Python installation(s) in PATH")

            for python_path in pythons:
                python_path = python_path.strip()
                if not python_path:
                    continue

                print(f"\n[CHECK] {python_path}")
                if is_valid_python(python_path):
                    return python_path
        else:
            print("[INFO] 'where python' found nothing in PATH")
    except Exception as e:
        print(f"[INFO] 'where python' failed: {e}")

    # Method 2: Check Windows Registry (only on Windows)
    if os.name == 'nt':
        print("\n[METHOD 2] Checking Windows Registry...")
        try:
            import winreg

            # Check both HKEY_CURRENT_USER and HKEY_LOCAL_MACHINE
            registry_keys = [
                (winreg.HKEY_CURRENT_USER, r"Software\Python\PythonCore"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Python\PythonCore"),
            ]

            for root_key, subkey_path in registry_keys:
                try:
                    with winreg.OpenKey(root_key, subkey_path) as key:
                        # Enumerate all Python versions
                        i = 0
                        while True:
                            try:
                                version = winreg.EnumKey(key, i)
                                print(f"[INFO] Found Python {version} in registry")

                                # Try to get install path
                                try:
                                    with winreg.OpenKey(key, f"{version}\\InstallPath") as install_key:
                                        install_path = winreg.QueryValue(install_key, None)
                                        python_exe = os.path.join(install_path, 'python.exe')

                                        print(f"[CHECK] {python_exe}")
                                        if is_valid_python(python_exe):
                                            return python_exe
                                except WindowsError:
                                    pass

                                i += 1
                            except WindowsError:
                                break
                except WindowsError:
                    pass
        except ImportError:
            print("[INFO] winreg not available (not on Windows)")
        except Exception as e:
            print(f"[INFO] Registry check failed: {e}")

    # Method 3: Check common installation locations
    print("\n[METHOD 3] Checking common installation paths...")
    common_paths = []

    if os.name == 'nt':
        # Windows common paths
        username = os.getenv('USERNAME', '')
        appdata = os.getenv('APPDATA', '')
        localappdata = os.getenv('LOCALAPPDATA', '')
        programfiles = os.getenv('ProgramFiles', 'C:\\Program Files')

        # Python.org installer locations
        for version in ['312', '311', '310', '39', '38', '37']:
            common_paths.extend([
                f"C:\\Python{version}\\python.exe",
                f"C:\\Users\\{username}\\AppData\\Local\\Programs\\Python\\Python{version}\\python.exe",
                f"{localappdata}\\Programs\\Python\\Python{version}\\python.exe",
            ])

        # Microsoft Store Python
        if localappdata:
            common_paths.append(f"{localappdata}\\Microsoft\\WindowsApps\\python.exe")

    for python_path in common_paths:
        if python_path and os.path.exists(python_path):
            print(f"[CHECK] {python_path}")
            if is_valid_python(python_path):
                return python_path

    # No Python found
    print("\n" + "=" * 60)
    print("[ERROR] Could not find Python on this system!")
    print("=" * 60)
    print("\nPlease ensure Python is installed:")
    print("1. Download Python from https://www.python.org/downloads/")
    print("2. Run the installer")
    print("3. IMPORTANT: Check 'Add Python to PATH' during installation")
    print("4. Restart this application after installing Python")
    print("=" * 60)
    return None

# Function to setup virtual environment with manim
def setup_venv(window=None):
    """
    Setup virtual environment in .manim_studio/venvs/manim_studio_default with manim installed.
    Returns path to venv Python executable.
    """
    import glob

    # Use the constant VENV_DIR for consistency
    venv_dir = VENV_DIR

    # Determine venv python path
    if os.name == 'nt':  # Windows
        venv_python = os.path.join(venv_dir, 'Scripts', 'python.exe')
    else:  # Linux/Mac
        venv_python = os.path.join(venv_dir, 'bin', 'python')

    print(f"[INFO] Virtual environment path: {venv_dir}")
    print(f"[INFO] Virtual environment Python: {venv_python}")

    # If venv exists and has Python, use it
    if os.path.exists(venv_python):
        print(f"[INFO] Using existing venv at: {venv_dir}")
        return venv_python

    # Need to create venv - find system Python first
    print("[INFO] Virtual environment not found, creating one...")

    system_python = find_system_python()
    if not system_python:
        error_title = "Python Not Found!"
        error_msgs = [
            "Could not find Python on this system.",
            "",
            "To fix this:",
            "1. Download Python from https://python.org/downloads/",
            "2. Run the installer",
            "3. IMPORTANT: Check 'Add Python to PATH' during installation",
            "4. Restart this application",
            "",
            "If Python is already installed, make sure it's added to your system PATH."
        ]

        print(f"[ERROR] {error_title}")
        for msg in error_msgs:
            print(f"        {msg}")

        if window:
            # Show error in console
            for msg in error_msgs:
                if msg:  # Skip empty lines
                    safe_msg = msg.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                    window.evaluate_js(f'if(window.appendConsole){{window.appendConsole("{safe_msg}", "error")}}')

            # Also show toast notification
            window.evaluate_js(f'if(window.toast){{window.toast("Python not found! Check console for details.", "error")}}')

        return None

    # CRITICAL SAFETY CHECK: Ensure we're NEVER using the exe itself
    if getattr(sys, 'frozen', False):
        exe_path = os.path.abspath(sys.executable)
        system_python_abs = os.path.abspath(system_python)
        if system_python_abs == exe_path:
            error_msg = f"CRITICAL ERROR: Attempted to use exe as Python! {system_python_abs}"
            print(f"[ERROR] {error_msg}")
            if window:
                window.evaluate_js(f'if(window.appendConsole){{window.appendConsole("{error_msg}", "error")}}')
            return None
        if 'manim' in os.path.basename(system_python_abs).lower():
            error_msg = f"CRITICAL ERROR: Python filename contains 'manim': {system_python_abs}"
            print(f"[ERROR] {error_msg}")
            if window:
                window.evaluate_js(f'if(window.appendConsole){{window.appendConsole("{error_msg}", "error")}}')
            return None

    print(f"[INFO] Found system Python: {system_python}")

    # Create venv
    os.makedirs(USER_DATA_DIR, exist_ok=True)

    def log_output(msg, level='info'):
        """Log to console and UI"""
        print(f"[{level.upper()}] {msg}")
        if window:
            safe_msg = msg.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
            window.evaluate_js(f'if(window.appendConsole){{window.appendConsole("{safe_msg}", "{level}")}}')

    try:
        log_output("=" * 60)
        log_output("STARTING VIRTUAL ENVIRONMENT CREATION")
        log_output("=" * 60)
        log_output("")
        log_output("Step 1: Creating virtual environment...")
        log_output("")

        # Create venv using clean environment with streaming output
        venv_process = subprocess.Popen(
            [system_python, '-m', 'venv', venv_dir, '--without-pip'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',  # Force UTF-8 encoding
            errors='replace',  # Replace invalid characters instead of crashing
            bufsize=1,
            universal_newlines=True,
            env=get_clean_environment(),  # Use clean environment
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # Stream output
        for line in iter(venv_process.stdout.readline, ''):
            if line:
                line = line.rstrip()
                log_output(line)

        venv_process.wait()

        if venv_process.returncode != 0:
            log_output("")
            log_output("Failed to create virtual environment!", "error")
            log_output("=" * 60)
            return None

        log_output("")
        log_output("✓ Virtual environment created successfully!")
        log_output("")

        # Now install pip
        log_output("Step 2: Installing pip in virtual environment...")
        log_output("")

        venv_python_exe = os.path.join(venv_dir, 'Scripts', 'python.exe') if os.name == 'nt' else os.path.join(venv_dir, 'bin', 'python')

        pip_install_process = subprocess.Popen(
            [venv_python_exe, '-m', 'ensurepip'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',  # Force UTF-8 encoding
            errors='replace',  # Replace invalid characters instead of crashing
            bufsize=1,
            universal_newlines=True,
            env=get_clean_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # Stream output
        for line in iter(pip_install_process.stdout.readline, ''):
            if line:
                line = line.rstrip()
                log_output(line)

        pip_install_process.wait()

        if pip_install_process.returncode != 0:
            log_output("")
            log_output("Failed to install pip!", "error")
            log_output("Trying alternative method...")
            log_output("")

        log_output("")
        log_output("✓ Pip installed successfully!")
        log_output("")

        # Install manim and manim-fonts
        log_output("Step 3: Installing Manim and fonts (this may take a few minutes)...")
        log_output("")

        # Use python -m pip instead of pip.exe directly for better compatibility
        install_process = subprocess.Popen(
            [venv_python_exe, '-m', 'pip', 'install', 'manim', 'manim-fonts'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',  # Force UTF-8 encoding
            errors='replace',  # Replace invalid characters instead of crashing
            bufsize=1,
            universal_newlines=True,
            env=get_clean_environment(),  # Use clean environment
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # Stream output to terminal
        for line in iter(install_process.stdout.readline, ''):
            if line:
                line = line.rstrip()
                log_output(line)

        install_process.wait()

        log_output("")
        if install_process.returncode == 0:
            log_output("✓ Manim and fonts installed successfully!", "success")
            log_output("")
            log_output("=" * 60)
            log_output("VIRTUAL ENVIRONMENT SETUP FINISHED!")
            log_output("=" * 60)
            log_output("")
            log_output("Summary:")
            log_output(f"  • Python: {system_python}")
            log_output(f"  • Venv location: {venv_dir}")
            log_output(f"  • Manim: Installed")
            log_output(f"  • Manim Fonts: Installed")
            log_output("")
            log_output("✓ Ready to render animations!")
            log_output("=" * 60)
            return venv_python
        else:
            log_output("✗ Failed to install manim or manim-fonts", "error")
            log_output("=" * 60)
            return None

    except Exception as e:
        log_output(f"Error setting up environment: {e}", "error")
        return None

# Function to get the Python interpreter
def get_python_executable(window=None):
    """
    Get the Python executable path.
    Always uses venv in .manim_studio, creating it if needed.
    NEVER RETURNS THE EXE ITSELF!
    """
    # If not frozen (running as script), check for venv
    if not getattr(sys, 'frozen', False):
        # Still use venv if available for consistency
        venv_python = setup_venv(window)
        if venv_python:
            return venv_python
        # Fallback to current Python
        return sys.executable

    # If frozen (compiled exe), MUST use venv - NEVER sys.executable!
    print("[INFO] Running as compiled exe - NEVER using exe itself for Python")
    print(f"[INFO] Exe path (WILL NOT USE): {sys.executable}")

    venv_python = setup_venv(window)

    if venv_python:
        print(f"[SUCCESS] Using venv Python: {venv_python}")
        return venv_python

    # Fallback - try to use 'python' from PATH as last resort
    # But NEVER return sys.executable when frozen!
    print("[ERROR] Could not setup Python environment!")
    print("[ERROR] Will try 'python' command as fallback (NOT the exe)")
    return 'python'

# Function to verify venv setup
def verify_venv_setup(window=None):
    """
    Verify that venv exists in .manim_studio and has manim installed.
    This forces a check at startup and logs all findings.
    """
    def log_msg(msg, level='info'):
        """Log to console and optionally to UI"""
        print(f"[{level.upper()}] {msg}")
        if window:
            safe_msg = msg.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
            window.evaluate_js(f'if(window.appendConsole){{window.appendConsole("{safe_msg}", "{level}")}}')

    log_msg("=" * 60)
    log_msg("VIRTUAL ENVIRONMENT VERIFICATION")
    log_msg("=" * 60)

    # Check venv directory
    log_msg(f"Checking venv location: {VENV_DIR}")

    if os.name == 'nt':  # Windows
        venv_python = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
        venv_pip = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
    else:  # Linux/Mac
        venv_python = os.path.join(VENV_DIR, 'bin', 'python')
        venv_pip = os.path.join(VENV_DIR, 'bin', 'pip')

    # Check if venv exists
    if not os.path.exists(VENV_DIR):
        log_msg("Virtual environment NOT found", "warning")
        log_msg("Will create on first render/preview", "info")
        log_msg("=" * 60)
        return False

    log_msg("Virtual environment directory EXISTS", "success")

    # Check if Python executable exists
    if not os.path.exists(venv_python):
        log_msg(f"Python executable NOT found at: {venv_python}", "error")
        log_msg("Venv may be corrupted - will recreate on next render", "warning")
        log_msg("=" * 60)
        return False

    log_msg(f"Python executable found: {venv_python}", "success")

    # Check if manim is installed
    try:
        log_msg("Checking if manim is installed in venv...")
        result = subprocess.run(
            [venv_pip, 'show', 'manim'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            env=get_clean_environment(),  # Use clean environment
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        if result.returncode == 0:
            # Parse manim version from output
            version_line = [line for line in result.stdout.split('\n') if line.startswith('Version:')]
            version = version_line[0].replace('Version:', '').strip() if version_line else 'unknown'
            log_msg(f"Manim is installed (version {version})", "success")
            log_msg("=" * 60)
            log_msg("VENV READY TO USE")
            log_msg("=" * 60)
            return True
        else:
            log_msg("Manim NOT installed in venv", "warning")
            log_msg("Will install on first render/preview", "info")
            log_msg("=" * 60)
            return False

    except Exception as e:
        log_msg(f"Error checking manim installation: {e}", "error")
        log_msg("=" * 60)
        return False

# Get the Python executable to use for manim
# Note: Will be re-initialized when window is available
PYTHON_EXE = None

# Application state
app_state = {
    'current_code': '',
    'current_file_path': None,
    'is_rendering': False,
    'is_previewing': False,
    'render_process': None,
    'preview_process': None,
    'output_dir': MEDIA_DIR,
    'window': None,
    'generated_files': [],  # Track files generated this session for cleanup
    'preview_files_to_cleanup': set(),  # Track preview MP4 files copied to assets for cleanup on exit
    'terminal_process': None,  # Persistent cmd.exe session
    'terminal_thread': None,  # Thread for reading terminal output
    'terminal_output_buffer': [],  # Buffer for terminal output
    'settings': {
        'quality': '720p',
        'format': 'MP4 Video',
        'fps': 30,
        'preview_quality': 'Medium',
        'theme': 'Dark+',
        'font_size': 14,
        'intellisense_enabled': True
    }
}

# Quality presets
QUALITY_PRESETS = {
    "4K": ("-qk", 3840, 2160),      # 4K quality (3840x2160 60fps)
    "2K": ("-qp", 2560, 1440),      # 2K quality (2560x1440 60fps)
    "1080p": ("-qh", 1920, 1080),   # High quality (1920x1080 60fps)
    "720p": ("-qm", 1280, 720),     # Medium quality (1280x720 30fps)
    "480p": ("-ql", 854, 480),      # Low quality (854x480 15fps)
}

def create_manim_config(script_dir):
    """Create manim.cfg in the script directory for proper asset path configuration"""
    config_path = os.path.join(script_dir, 'manim.cfg')
    config_content = f"""[CLI]
# Manim Studio Configuration
assets_dir = {ASSETS_DIR}
media_dir = {MEDIA_DIR}
"""
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        print(f"[CONFIG] Created manim.cfg at: {config_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to create manim.cfg: {e}")
        return False

def clear_preview_folder():
    """Clear all files in the preview folder before each preview"""
    import shutil
    try:
        if os.path.exists(PREVIEW_DIR):
            # Remove all contents
            for item in os.listdir(PREVIEW_DIR):
                item_path = os.path.join(PREVIEW_DIR, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    print(f"[WARNING] Failed to delete {item_path}: {e}")
            print(f"[OK] Cleared preview folder: {PREVIEW_DIR}")
        else:
            # Create if doesn't exist
            os.makedirs(PREVIEW_DIR, exist_ok=True)
            print(f"[OK] Created preview folder: {PREVIEW_DIR}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to clear preview folder: {e}")
        return False

def clear_render_folder():
    """Clear all files in the render folder before each render"""
    import shutil
    try:
        if os.path.exists(RENDER_DIR):
            # Remove all contents
            for item in os.listdir(RENDER_DIR):
                item_path = os.path.join(RENDER_DIR, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    print(f"[WARNING] Failed to delete {item_path}: {e}")
            print(f"[OK] Cleared render folder: {RENDER_DIR}")
        else:
            # Create if doesn't exist
            os.makedirs(RENDER_DIR, exist_ok=True)
            print(f"[OK] Created render folder: {RENDER_DIR}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to clear render folder: {e}")
        return False

def load_settings():
    """Load settings from file"""
    settings_file = os.path.join(BASE_DIR, 'settings.json')
    try:
        if os.path.exists(settings_file):
            with open(settings_file, 'r') as f:
                saved = json.load(f)
                app_state['settings'].update(saved)
    except Exception as e:
        print(f"Error loading settings: {e}")

def save_settings():
    """Save settings to file"""
    settings_file = os.path.join(BASE_DIR, 'settings.json')
    try:
        with open(settings_file, 'w') as f:
            json.dump(app_state['settings'], f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")

def extract_scene_name(code):
    """Extract the scene class name from code"""
    match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', code)
    return match.group(1) if match else None

class ManimAPI:
    """
    API class that exposes Python functions to JavaScript
    All methods in this class can be called from JS using: pywebview.api.method_name()
    """

    def __init__(self):
        """Initialize the API"""
        # AI/LLM feature removed

        # Start terminal automatically
        print("[API] Auto-starting persistent terminal...")
        try:
            self.start_persistent_terminal()
        except Exception as e:
            print(f"[API ERROR] Failed to auto-start terminal: {e}")

    def get_code(self):
        """Get current code"""
        return {'code': app_state['current_code']}

    def set_code(self, code):
        """Set current code"""
        app_state['current_code'] = code
        return {'status': 'success'}

    def new_file(self):
        """Create a new file"""
        app_state['current_code'] = """from manim import *

class MyScene(Scene):
    def construct(self):
        # Your animation code here
        text = Text("Hello, Manim!")
        self.play(Write(text))
        self.wait()
"""
        app_state['current_file_path'] = None
        return {'status': 'success', 'code': app_state['current_code']}

    def open_file_dialog(self):
        """Open file dialog and return file path"""
        result = app_state['window'].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('Python Files (*.py)',)
        )

        if result and len(result) > 0:
            file_path = result[0]
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                app_state['current_code'] = content
                app_state['current_file_path'] = file_path
                return {'status': 'success', 'code': content, 'path': file_path, 'filename': os.path.basename(file_path)}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

        return {'status': 'cancelled'}

    def save_file_dialog(self, code):
        """Save file dialog"""
        result = app_state['window'].create_file_dialog(
            dialog_type=webview.SAVE_DIALOG,
            save_filename='scene.py',
            file_types=('Python Files (*.py)',)
        )

        if result:
            file_path = result
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code)

                app_state['current_code'] = code
                app_state['current_file_path'] = file_path
                return {'status': 'success', 'path': file_path, 'filename': os.path.basename(file_path)}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}

        return {'status': 'cancelled'}

    def save_file(self, code, file_path=None):
        """Save the current file"""
        if not file_path:
            file_path = app_state.get('current_file_path')

        if not file_path:
            return self.save_file_dialog(code)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)

            app_state['current_code'] = code
            app_state['current_file_path'] = file_path
            return {'status': 'success', 'path': file_path, 'filename': os.path.basename(file_path)}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def autosave_code(self, code):
        """Auto-save code to temporary location"""
        try:
            import json
            from datetime import datetime

            # Create autosave directory
            os.makedirs(AUTOSAVE_DIR, exist_ok=True)

            # Generate timestamp-based filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            autosave_file = os.path.join(AUTOSAVE_DIR, f'autosave_{timestamp}.py')

            # Save code
            with open(autosave_file, 'w', encoding='utf-8') as f:
                f.write(code)

            # Save metadata
            metadata = {
                'timestamp': timestamp,
                'file_path': app_state.get('current_file_path', ''),
                'autosave_file': autosave_file
            }

            metadata_file = os.path.join(AUTOSAVE_DIR, f'autosave_{timestamp}.json')
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            # Keep only last 5 autosaves
            self.cleanup_old_autosaves()

            print(f"[AUTOSAVE] Saved to {autosave_file}")
            return {'status': 'success', 'file': autosave_file, 'timestamp': timestamp}

        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def cleanup_old_autosaves(self):
        """Keep only the last 5 autosaves"""
        try:
            # Get all autosave files
            autosave_files = []
            for filename in os.listdir(AUTOSAVE_DIR):
                if filename.startswith('autosave_') and filename.endswith('.py'):
                    filepath = os.path.join(AUTOSAVE_DIR, filename)
                    autosave_files.append((filepath, os.path.getmtime(filepath)))

            # Sort by modification time (newest first)
            autosave_files.sort(key=lambda x: x[1], reverse=True)

            # Delete old autosaves (keep only 5 newest)
            for filepath, _ in autosave_files[5:]:
                try:
                    os.remove(filepath)
                    # Also remove corresponding metadata file
                    metadata_file = filepath.replace('.py', '.json')
                    if os.path.exists(metadata_file):
                        os.remove(metadata_file)
                    print(f"[AUTOSAVE] Deleted old autosave: {filepath}")
                except Exception as e:
                    print(f"[AUTOSAVE] Error deleting {filepath}: {e}")

        except Exception as e:
            print(f"[AUTOSAVE CLEANUP ERROR] {e}")

    def get_autosave_files(self):
        """Get list of available autosave files"""
        try:
            import json

            if not os.path.exists(AUTOSAVE_DIR):
                return {'status': 'success', 'files': []}

            autosaves = []
            for filename in os.listdir(AUTOSAVE_DIR):
                if filename.startswith('autosave_') and filename.endswith('.json'):
                    metadata_file = os.path.join(AUTOSAVE_DIR, filename)
                    try:
                        with open(metadata_file, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)

                        # Check if corresponding .py file exists
                        py_file = metadata.get('autosave_file', '')
                        if os.path.exists(py_file):
                            autosaves.append(metadata)
                    except Exception as e:
                        print(f"[AUTOSAVE] Error reading metadata {filename}: {e}")

            # Sort by timestamp (newest first)
            autosaves.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

            return {'status': 'success', 'files': autosaves}

        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def load_autosave(self, autosave_file):
        """Load code from an autosave file"""
        try:
            if not os.path.exists(autosave_file):
                return {'status': 'error', 'message': 'Autosave file not found'}

            with open(autosave_file, 'r', encoding='utf-8') as f:
                code = f.read()

            print(f"[AUTOSAVE] Loaded from {autosave_file}")
            return {'status': 'success', 'code': code}

        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def delete_autosave(self, autosave_file):
        """Delete a specific autosave file"""
        try:
            if os.path.exists(autosave_file):
                os.remove(autosave_file)
                # Also remove metadata
                metadata_file = autosave_file.replace('.py', '.json')
                if os.path.exists(metadata_file):
                    os.remove(metadata_file)
                print(f"[AUTOSAVE] Deleted {autosave_file}")
                return {'status': 'success'}
            else:
                return {'status': 'error', 'message': 'File not found'}
        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def check_code_errors(self, code):
        """Check Python code for syntax errors using AST"""
        try:
            import ast
            import traceback

            errors = []

            if not code.strip():
                return {'status': 'success', 'errors': errors}

            try:
                # Try to parse the code
                ast.parse(code)
                # No errors found
                return {'status': 'success', 'errors': []}

            except SyntaxError as e:
                # Syntax error found
                error_info = {
                    'type': 'error',
                    'line': e.lineno if e.lineno else 0,
                    'column': e.offset if e.offset else 0,
                    'message': str(e.msg),
                    'text': e.text.strip() if e.text else ''
                }
                errors.append(error_info)

            except Exception as e:
                # Other parsing errors
                error_info = {
                    'type': 'error',
                    'line': 0,
                    'column': 0,
                    'message': str(e),
                    'text': ''
                }
                errors.append(error_info)

            return {'status': 'success', 'errors': errors}

        except Exception as e:
            print(f"[CODE CHECK ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def render_animation(self, code, quality='720p', fps=30, format='mp4', width=None, height=None):
        """Render the animation - same as preview but uses RENDER_DIR"""
        global PYTHON_EXE

        # Initialize Python executable if needed
        if PYTHON_EXE is None:
            PYTHON_EXE = get_python_executable(app_state['window'])
            if not PYTHON_EXE:
                return {'status': 'error', 'message': 'Python environment not available'}

        if app_state['is_rendering']:
            return {'status': 'error', 'message': 'Already rendering'}

        try:
            # Clear render folder before rendering
            print("[RENDER] Clearing render folder...")
            clear_render_folder()

            # Create temporary file in render folder
            os.makedirs(RENDER_DIR, exist_ok=True)
            timestamp = int(time.time() * 1000)
            temp_file = os.path.join(RENDER_DIR, f'temp_render_{timestamp}.py')

            # Write file and ensure it's fully closed before proceeding
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)
                f.flush()  # Flush to OS buffer
                os.fsync(f.fileno())  # Force write to disk

            # Ensure file is flushed to disk and fully closed
            time.sleep(0.2)  # Increased delay to ensure file is available

            # Verify file was created
            if not os.path.exists(temp_file):
                return {'status': 'error', 'message': f'Failed to create temporary file: {temp_file}'}

            print(f"[RENDER] Created temp file: {temp_file}")

            # Create manim.cfg in the render directory
            create_manim_config(RENDER_DIR)

            scene_name = extract_scene_name(code)
            if not scene_name:
                return {'status': 'error', 'message': 'No scene class found'}

            # Get manim executable path (in venv Scripts folder)
            if os.name == 'nt':
                manim_exe = os.path.join(VENV_DIR, 'Scripts', 'manim.exe')
            else:
                manim_exe = os.path.join(VENV_DIR, 'bin', 'manim')

            # Fallback to python -m manim if executable not found
            if not os.path.exists(manim_exe):
                print(f"[WARNING] Manim executable not found at {manim_exe}, using python -m manim")
                cmd = [PYTHON_EXE, '-m', 'manim']
            else:
                cmd = [manim_exe]

            # Convert quality preset to flag
            quality_flag = self._get_quality_flag(quality)

            # Add file, scene, and quality flag
            cmd.extend([temp_file, scene_name, quality_flag])

            # Add render directory as media directory (output goes here)
            cmd.extend(['--media_dir', RENDER_DIR])

            # Add FPS if not using preset quality flag
            if quality_flag not in ['-ql', '-qm', '-qh', '-qp', '-qk']:
                cmd.extend(['--frame_rate', str(fps)])

            # Add format if specified
            if format and format.lower() != 'mp4':
                cmd.extend(['--format', format.lower()])

            print(f"Render command: {' '.join(cmd)}")

            # Send command to terminal PTY instead of running in subprocess
            # Terminal is in ASSETS_DIR, but render temp file is in RENDER_DIR, so we need full paths
            # Build command string with proper quoting
            cmd_parts = []
            for arg in cmd:
                # Quote arguments that have spaces or are paths
                if ' ' in arg or arg == temp_file or '\\' in arg:
                    cmd_parts.append(f'"{arg}"')
                else:
                    cmd_parts.append(arg)

            cmd_string = ' '.join(cmd_parts)
            print(f"[RENDER] Sending to terminal: {cmd_string}")

            if app_state['terminal_process'] is not None:
                try:
                    # Clear terminal before running new render to remove old errors
                    if WINPTY_AVAILABLE and hasattr(app_state['terminal_process'], 'write'):
                        app_state['terminal_process'].write('cls\r\n')
                        time.sleep(0.2)

                    # Send command to terminal
                    if WINPTY_AVAILABLE and hasattr(app_state['terminal_process'], 'write'):
                        app_state['terminal_process'].write(cmd_string + '\r\n')
                    else:
                        app_state['terminal_process'].stdin.write(cmd_string + '\n')
                        app_state['terminal_process'].stdin.flush()

                    app_state['is_rendering'] = True

                    # Store temp file path for cleanup after render
                    render_temp_file = temp_file

                    # Start a background thread to watch for render file and handle it
                    def watch_render():
                        import time
                        import shutil
                        max_wait = 300  # 5 minutes for render
                        start_time = time.time()

                        print(f"[RENDER WATCHER] Waiting for render to complete...")
                        print(f"[RENDER WATCHER] Temp file to clean up later: {render_temp_file}")

                        # Wait for file to appear in render directory
                        while time.time() - start_time < max_wait:
                            time.sleep(2)

                            # Look for video files in render directory
                            try:
                                videos_dir = os.path.join(RENDER_DIR, 'videos')
                                if os.path.exists(videos_dir):
                                    for root, dirs, files in os.walk(videos_dir):
                                        for file in files:
                                            # Skip partial movie files - only look for the final combined MP4
                                            if file.endswith('.mp4') and 'partial_movie_files' not in root:
                                                render_file = os.path.join(root, file)
                                                print(f"[RENDER WATCHER] Found render file: {render_file}")

                                                # Wait a bit more to ensure manim has completely finished writing
                                                print(f"[RENDER WATCHER] Waiting for manim to finish completely...")
                                                time.sleep(3)  # Wait for manim to fully complete and release file

                                                # Verify file is not being written to
                                                file_size_1 = os.path.getsize(render_file)
                                                time.sleep(1)
                                                file_size_2 = os.path.getsize(render_file)

                                                if file_size_1 != file_size_2:
                                                    # File is still being written, wait more
                                                    print(f"[RENDER WATCHER] File still being written, waiting more...")
                                                    continue

                                                # Move MP4 directly to RENDER_DIR root
                                                try:
                                                    final_render_path = os.path.join(RENDER_DIR, file)

                                                    print(f"[RENDER WATCHER] Moving MP4 to root directory...")
                                                    shutil.move(render_file, final_render_path)
                                                    print(f"[RENDER WATCHER] Moved to: {final_render_path}")

                                                    # Remove the videos folder structure created by manim
                                                    print(f"[RENDER WATCHER] Removing manim folder structure...")
                                                    try:
                                                        if os.path.exists(videos_dir):
                                                            shutil.rmtree(videos_dir)
                                                            print(f"[RENDER WATCHER] Removed videos folder")
                                                    except Exception as rmdir_err:
                                                        print(f"[RENDER WATCHER] Could not remove videos dir: {rmdir_err}")

                                                    # Clean up temp file after successful render
                                                    try:
                                                        if os.path.exists(render_temp_file):
                                                            os.remove(render_temp_file)
                                                            print(f"[RENDER WATCHER] Cleaned up temp .py file")
                                                    except Exception as cleanup_err:
                                                        print(f"[RENDER WATCHER] Error cleaning temp file: {cleanup_err}")

                                                    app_state['is_rendering'] = False
                                                    print(f"[RENDER WATCHER] Render complete! File ready at: {final_render_path}")

                                                    # Show save dialog to user AFTER everything is done
                                                    try:
                                                        if app_state['window']:
                                                            # Small delay to ensure everything is settled
                                                            time.sleep(0.5)
                                                            # Trigger save dialog in frontend with final path
                                                            escaped_path = final_render_path.replace('\\', '\\\\').replace('"', '\\"')
                                                            app_state['window'].evaluate_js(
                                                                f'if(window.showRenderSaveDialog){{window.showRenderSaveDialog("{escaped_path}")}}'
                                                            )
                                                            print(f"[RENDER WATCHER] Save dialog triggered")
                                                    except Exception as dialog_err:
                                                        print(f"[RENDER WATCHER] Error showing save dialog: {dialog_err}")

                                                    return
                                                except Exception as move_err:
                                                    print(f"[RENDER WATCHER ERROR] Failed to move/cleanup: {move_err}")

                            except Exception as e:
                                print(f"[RENDER WATCHER] Error checking files: {e}")

                        print(f"[RENDER WATCHER] Timeout - render file not found after {max_wait}s")
                        app_state['is_rendering'] = False

                        # Clean up temp file even on timeout
                        try:
                            if os.path.exists(render_temp_file):
                                os.remove(render_temp_file)
                                print(f"[RENDER WATCHER] Cleaned up temp file after timeout: {render_temp_file}")
                        except Exception as cleanup_err:
                            print(f"[RENDER WATCHER] Error cleaning temp file: {cleanup_err}")

                    import threading
                    watcher_thread = threading.Thread(target=watch_render, daemon=True)
                    watcher_thread.start()

                    return {'status': 'started', 'message': 'Render command sent to terminal'}
                except Exception as e:
                    print(f"[RENDER ERROR] Failed to send to terminal: {e}")
                    return {'status': 'error', 'message': f'Failed to send command to terminal: {e}'}

            # Fallback to old subprocess method if terminal not available
            print("[RENDER] Terminal not available, using fallback subprocess method")

            # Start rendering in background thread
            def render_thread():
                app_state['is_rendering'] = True
                output_lines = []

                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',  # Force UTF-8 encoding
                        errors='replace',  # Replace invalid characters instead of crashing
                        bufsize=1,
                        universal_newlines=True,
                        env=get_clean_environment(),  # Use clean environment
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )

                    app_state['render_process'] = process

                    # Read output line by line
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            line = line.rstrip()
                            output_lines.append(line)
                            print(f"[Render] {line}")

                            # Send to UI using evaluate_js
                            if app_state['window']:
                                try:
                                    safe_line = line.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '\\n')
                                    app_state['window'].evaluate_js(
                                        f'if(window.updateRenderOutput){{window.updateRenderOutput("{safe_line}")}}'
                                    )
                                except Exception as e:
                                    # Ignore errors when window is disposed/closed
                                    if "disposed" not in str(e).lower():
                                        print(f"[RENDER] Error updating output: {e}")

                    process.wait()

                    print(f"Render process finished with code: {process.returncode}")

                    if process.returncode == 0:
                        # Wait a moment for filesystem to flush files to disk
                        print("[INFO] Waiting for files to be written to disk...")
                        time.sleep(2)  # Give OS time to flush buffers

                        # Find the rendered files
                        final_path = self.cleanup_after_render(scene_name)

                        # Verify file actually exists and is readable before proceeding
                        if final_path and os.path.exists(final_path):
                            try:
                                # Try to open and verify the file is accessible
                                with open(final_path, 'rb') as f:
                                    f.read(1)  # Read one byte to verify it's accessible
                                print(f"[OK] Verified file exists and is accessible: {final_path}")
                            except Exception as verify_error:
                                print(f"[ERROR] File exists but not accessible: {verify_error}")
                                final_path = None
                        else:
                            print(f"[WARNING] No output file found after render")

                        # Move to assets folder and trigger auto-save dialog
                        if final_path:
                            try:
                                import shutil
                                from datetime import datetime

                                # Create timestamp for unique filename
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                original_name = os.path.basename(final_path)
                                name_without_ext = os.path.splitext(original_name)[0]
                                ext = os.path.splitext(original_name)[1]

                                # Create assets folder if it doesn't exist
                                os.makedirs(ASSETS_DIR, exist_ok=True)

                                # Move to assets with timestamp
                                assets_filename = f"{name_without_ext}_{timestamp}{ext}"
                                assets_path = os.path.join(ASSETS_DIR, assets_filename)

                                print(f"[INFO] Moving rendered file to assets folder...")
                                print(f"   From: {final_path}")
                                print(f"   To: {assets_path}")

                                shutil.move(final_path, assets_path)
                                print(f"[OK] File moved to assets!")

                                # Clean up temp folders now that file is safe in assets
                                print(f"[INFO] Cleaning up temp folders...")
                                videos_base = os.path.join(MEDIA_DIR, 'videos')
                                images_base = os.path.join(MEDIA_DIR, 'images')
                                folders_deleted = 0

                                # Delete temp folders from videos
                                if os.path.exists(videos_base):
                                    for folder in os.listdir(videos_base):
                                        if folder.startswith('temp_'):
                                            folder_path = os.path.join(videos_base, folder)
                                            try:
                                                shutil.rmtree(folder_path)
                                                folders_deleted += 1
                                                print(f"   [OK] Deleted: {folder}")
                                            except Exception as e:
                                                print(f"   [ERROR] Failed to delete {folder}: {e}")

                                # Delete temp folders from images
                                if os.path.exists(images_base):
                                    for folder in os.listdir(images_base):
                                        if folder.startswith('temp_'):
                                            folder_path = os.path.join(images_base, folder)
                                            try:
                                                shutil.rmtree(folder_path)
                                                folders_deleted += 1
                                                print(f"   [OK] Deleted: {folder}")
                                            except Exception as e:
                                                print(f"   [ERROR] Failed to delete {folder}: {e}")

                                print(f"[OK] Cleaned up {folders_deleted} temp folder(s)")

                                # Call renderCompleted with autoSave flag
                                if app_state['window']:
                                    safe_path = assets_path.replace('\\', '/').replace('"', '\\"')
                                    # Format: scene name with timestamp as suggested filename
                                    suggested_name = f"{scene_name}_{timestamp}.mp4"
                                    safe_name = suggested_name.replace('"', '\\"')
                                    app_state['window'].evaluate_js(
                                        f'if(window.renderCompleted){{window.renderCompleted("{safe_path}", true, "{safe_name}")}}'
                                    )
                            except Exception as move_error:
                                print(f"[ERROR] Failed to move file to assets: {move_error}")
                                # Fall back to old behavior if move fails
                                if app_state['window']:
                                    safe_path = final_path.replace('\\', '/').replace('"', '\\"')
                                    app_state['window'].evaluate_js(
                                        f'if(window.renderCompleted){{window.renderCompleted("{safe_path}")}}'
                                    )
                        else:
                            # No file found
                            if app_state['window']:
                                app_state['window'].evaluate_js(
                                    'if(window.renderCompleted){window.renderCompleted()}'
                                )

                        result = {
                            'status': 'success',
                            'message': 'Rendering completed',
                            'output': '\n'.join(output_lines)
                        }
                    else:
                        if app_state['window']:
                            error_msg = f"Render failed with code {process.returncode}".replace('"', '\\"')
                            app_state['window'].evaluate_js(
                                f'if(window.renderFailed){{window.renderFailed("{error_msg}")}}'
                            )
                        result = {
                            'status': 'error',
                            'message': f'Render failed with code {process.returncode}',
                            'output': '\n'.join(output_lines)
                        }

                except Exception as e:
                    print(f"Render error: {e}")
                    if app_state['window']:
                        safe_error = str(e).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        app_state['window'].evaluate_js(
                            f'if(window.renderFailed){{window.renderFailed("{safe_error}")}}'
                        )
                    result = {
                        'status': 'error',
                        'message': str(e),
                        'output': '\n'.join(output_lines)
                    }
                finally:
                    app_state['is_rendering'] = False
                    # Clean up temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass

            threading.Thread(target=render_thread, daemon=True).start()

            return {'status': 'started', 'message': 'Rendering started', 'scene': scene_name}

        except Exception as e:
            print(f"Error starting render: {e}")
            return {'status': 'error', 'message': str(e)}

    def _get_quality_flag(self, quality):
        """Convert quality preset to manim flag or custom resolution"""
        if quality in QUALITY_PRESETS:
            return QUALITY_PRESETS[quality][0]  # Return the flag (e.g., '-ql', '-qm')
        else:
            # Custom resolution format: WIDTHxHEIGHT
            return f'-r{quality}'

    def quick_preview(self, code, quality='480p', fps=15, format='mp4'):
        """Quick preview the animation with customizable quality settings"""
        global PYTHON_EXE

        # Initialize Python executable if needed
        if PYTHON_EXE is None:
            PYTHON_EXE = get_python_executable(app_state['window'])
            if not PYTHON_EXE:
                return {'status': 'error', 'message': 'Python environment not available'}

        if app_state['is_previewing']:
            return {'status': 'error', 'message': 'Already previewing'}

        try:
            # Clear preview folder before rendering
            print("[PREVIEW] Clearing preview folder...")
            clear_preview_folder()

            # Create temporary file in preview folder
            os.makedirs(PREVIEW_DIR, exist_ok=True)
            timestamp = int(time.time() * 1000)
            temp_file = os.path.join(PREVIEW_DIR, f'temp_preview_{timestamp}.py')

            # Write file and ensure it's fully closed before proceeding
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)
                f.flush()  # Flush to OS buffer
                os.fsync(f.fileno())  # Force write to disk

            # Ensure file is flushed to disk and fully closed
            time.sleep(0.2)  # Increased delay to ensure file is available

            # Verify file was created
            if not os.path.exists(temp_file):
                return {'status': 'error', 'message': f'Failed to create temporary file: {temp_file}'}

            print(f"[PREVIEW] Created temp file: {temp_file}")

            # Create manim.cfg in the preview directory
            create_manim_config(PREVIEW_DIR)

            scene_name = extract_scene_name(code)
            if not scene_name:
                return {'status': 'error', 'message': 'No scene class found'}

            # Get manim executable path (in venv Scripts folder)
            if os.name == 'nt':
                manim_exe = os.path.join(VENV_DIR, 'Scripts', 'manim.exe')
            else:
                manim_exe = os.path.join(VENV_DIR, 'bin', 'manim')

            # Fallback to python -m manim if executable not found
            if not os.path.exists(manim_exe):
                print(f"[WARNING] Manim executable not found at {manim_exe}, using python -m manim")
                cmd = [PYTHON_EXE, '-m', 'manim']
            else:
                cmd = [manim_exe]

            # Convert quality preset to flag or resolution
            quality_flag = self._get_quality_flag(quality)

            # Add file, scene, and quality flag
            cmd.extend([temp_file, scene_name, quality_flag])

            # Add preview directory as media directory (output goes here)
            cmd.extend(['--media_dir', PREVIEW_DIR])

            # Add FPS if not using preset quality flag
            if quality_flag not in ['-ql', '-qm', '-qh', '-qp', '-qk']:
                cmd.extend(['--frame_rate', str(fps)])

            # Add format if specified
            if format and format.lower() != 'mp4':
                cmd.extend(['--format', format.lower()])

            print(f"Preview command: {' '.join(cmd)}")

            # Send command to terminal PTY instead of running in subprocess
            # Terminal is in ASSETS_DIR, but preview temp file is in PREVIEW_DIR, so we need full paths
            # Build command string with proper quoting
            cmd_parts = []
            for arg in cmd:
                # Quote arguments that have spaces or are paths
                if ' ' in arg or arg == temp_file or '\\' in arg:
                    cmd_parts.append(f'"{arg}"')
                else:
                    cmd_parts.append(arg)

            cmd_string = ' '.join(cmd_parts)
            print(f"[PREVIEW] Sending to terminal: {cmd_string}")

            if app_state['terminal_process'] is not None:
                try:
                    # Clear terminal before running new preview to remove old errors
                    if WINPTY_AVAILABLE and hasattr(app_state['terminal_process'], 'write'):
                        app_state['terminal_process'].write('cls\r\n')
                        time.sleep(0.2)

                    # Send command to terminal
                    if WINPTY_AVAILABLE and hasattr(app_state['terminal_process'], 'write'):
                        app_state['terminal_process'].write(cmd_string + '\r\n')
                    else:
                        app_state['terminal_process'].stdin.write(cmd_string + '\n')
                        app_state['terminal_process'].stdin.flush()

                    app_state['is_previewing'] = True

                    # Store temp file path for cleanup after preview
                    preview_temp_file = temp_file

                    # Start a background thread to watch for preview file and handle it
                    def watch_preview():
                        import time
                        import shutil
                        max_wait = 180  # 3 minutes for preview
                        start_time = time.time()

                        print(f"[PREVIEW WATCHER] Waiting for preview to complete...")
                        print(f"[PREVIEW WATCHER] Temp file to clean up later: {preview_temp_file}")

                        # Wait for file to appear in preview directory
                        while time.time() - start_time < max_wait:
                            time.sleep(2)

                            # Look for video files in preview directory
                            try:
                                videos_dir = os.path.join(PREVIEW_DIR, 'videos')
                                if os.path.exists(videos_dir):
                                    for root, dirs, files in os.walk(videos_dir):
                                        for file in files:
                                            # Skip partial movie files - only look for the final combined MP4
                                            if file.endswith('.mp4') and 'partial_movie_files' not in root:
                                                preview_file = os.path.join(root, file)
                                                print(f"[PREVIEW WATCHER] Found preview file: {preview_file}")

                                                # Copy preview file to assets and track for cleanup on exit
                                                try:
                                                    os.makedirs(ASSETS_DIR, exist_ok=True)
                                                    assets_path = os.path.join(ASSETS_DIR, file)

                                                    # If file already exists, remove it first
                                                    if os.path.exists(assets_path):
                                                        os.remove(assets_path)

                                                    print(f"[PREVIEW WATCHER] Copying to assets: {assets_path}")
                                                    shutil.copy2(preview_file, assets_path)
                                                    print(f"[PREVIEW WATCHER] Preview file copied to assets!")

                                                    # Add to cleanup set - will be deleted when app closes
                                                    app_state['preview_files_to_cleanup'].add(assets_path)
                                                    print(f"[PREVIEW WATCHER] Added to cleanup set (total: {len(app_state['preview_files_to_cleanup'])} files)")

                                                    # Notify frontend to load preview in preview box
                                                    if app_state['window']:
                                                        try:
                                                            # Escape the path for JavaScript
                                                            escaped_path = assets_path.replace('\\', '\\\\').replace('"', '\\"')
                                                            app_state['window'].evaluate_js(
                                                                f'if(window.previewCompleted){{window.previewCompleted("{escaped_path}")}}'
                                                            )
                                                            print(f"[PREVIEW WATCHER] Notified frontend to load preview")
                                                        except Exception as js_err:
                                                            print(f"[PREVIEW WATCHER] Error notifying frontend: {js_err}")

                                                    app_state['is_previewing'] = False

                                                    # Clean up temp file after successful preview
                                                    try:
                                                        if os.path.exists(preview_temp_file):
                                                            os.remove(preview_temp_file)
                                                            print(f"[PREVIEW WATCHER] Cleaned up temp file: {preview_temp_file}")
                                                    except Exception as cleanup_err:
                                                        print(f"[PREVIEW WATCHER] Error cleaning temp file: {cleanup_err}")

                                                    return
                                                except Exception as copy_err:
                                                    print(f"[PREVIEW WATCHER ERROR] Failed to copy preview file: {copy_err}")

                            except Exception as e:
                                print(f"[PREVIEW WATCHER] Error checking files: {e}")

                        print(f"[PREVIEW WATCHER] Timeout - preview file not found after {max_wait}s")
                        app_state['is_previewing'] = False

                        # Clean up temp file even on timeout
                        try:
                            if os.path.exists(preview_temp_file):
                                os.remove(preview_temp_file)
                                print(f"[PREVIEW WATCHER] Cleaned up temp file after timeout: {preview_temp_file}")
                        except Exception as cleanup_err:
                            print(f"[PREVIEW WATCHER] Error cleaning temp file: {cleanup_err}")

                    import threading
                    watcher_thread = threading.Thread(target=watch_preview, daemon=True)
                    watcher_thread.start()

                    return {'status': 'started', 'message': 'Preview command sent to terminal'}
                except Exception as e:
                    print(f"[PREVIEW ERROR] Failed to send to terminal: {e}")
                    return {'status': 'error', 'message': f'Failed to send command to terminal: {e}'}

            # Fallback to old subprocess method if terminal not available
            print("[PREVIEW] Terminal not available, using fallback subprocess method")

            def preview_thread():
                app_state['is_previewing'] = True
                output_lines = []

                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',  # Force UTF-8 encoding
                        errors='replace',  # Replace invalid characters instead of crashing
                        bufsize=1,
                        universal_newlines=True,
                        env=get_clean_environment(),  # Use clean environment
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )

                    app_state['preview_process'] = process

                    # Read output
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            line = line.rstrip()
                            output_lines.append(line)
                            print(f"[Preview] {line}")

                            if app_state['window']:
                                try:
                                    safe_line = line.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '\\n')
                                    app_state['window'].evaluate_js(
                                        f'if(window.updateRenderOutput){{window.updateRenderOutput("{safe_line}")}}'
                                    )
                                except Exception as e:
                                    # Ignore errors when window is disposed/closed
                                    if "disposed" not in str(e).lower():
                                        print(f"[PREVIEW] Error updating output: {e}")

                    process.wait()

                    print(f"Preview finished with code: {process.returncode}")

                    if process.returncode == 0:
                        # Wait a moment for filesystem to flush files to disk
                        print("[INFO] Waiting for files to be written to disk...")
                        time.sleep(2)  # Give OS time to flush buffers

                        # Find the rendered files in preview directory
                        final_path = self.cleanup_after_render(scene_name, media_dir=PREVIEW_DIR)

                        # Verify file actually exists and is readable before proceeding
                        if final_path and os.path.exists(final_path):
                            try:
                                # Try to open and verify the file is accessible
                                with open(final_path, 'rb') as f:
                                    f.read(1)  # Read one byte to verify it's accessible
                                print(f"[OK] Verified file exists and is accessible: {final_path}")
                                print(f"[OK] Preview file ready in preview folder: {final_path}")

                            except Exception as verify_error:
                                print(f"[ERROR] Failed to verify preview file: {verify_error}")
                                final_path = None
                        else:
                            print(f"[WARNING] No output file found after preview")

                        if app_state['window']:
                            if final_path:
                                safe_path = final_path.replace('\\', '/').replace('"', '\\"')
                                app_state['window'].evaluate_js(
                                    f'if(window.previewCompleted){{window.previewCompleted("{safe_path}")}}'
                                )
                            else:
                                app_state['window'].evaluate_js(
                                    'if(window.previewCompleted){window.previewCompleted()}'
                                )
                    else:
                        if app_state['window']:
                            error_msg = f"Preview failed with code {process.returncode}".replace('"', '\\"')
                            app_state['window'].evaluate_js(
                                f'if(window.previewFailed){{window.previewFailed("{error_msg}")}}'
                            )

                except Exception as e:
                    print(f"Preview error: {e}")
                    if app_state['window']:
                        safe_error = str(e).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
                        app_state['window'].evaluate_js(
                            f'if(window.previewFailed){{window.previewFailed("{safe_error}")}}'
                        )
                finally:
                    app_state['is_previewing'] = False
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass

            threading.Thread(target=preview_thread, daemon=True).start()

            return {'status': 'started', 'message': 'Preview started', 'scene': scene_name}

        except Exception as e:
            print(f"Error starting preview: {e}")
            return {'status': 'error', 'message': str(e)}

    def stop_render(self):
        """Stop current render"""
        if app_state['render_process']:
            try:
                app_state['render_process'].terminate()
                app_state['is_rendering'] = False
                return {'status': 'success'}
            except Exception as e:
                return {'status': 'error', 'message': str(e)}
        return {'status': 'error', 'message': 'No render process running'}

    def cleanup_after_render(self, scene_name, temp_filename=None, media_dir=None):
        """Find rendered files and return path - DO NOT auto-save, let user choose location"""
        try:
            import shutil

            # Use provided media_dir or default to MEDIA_DIR
            if media_dir is None:
                media_dir = MEDIA_DIR

            print("=" * 60)
            print(f"[CLEANUP] FINDING RENDERED FILES for scene: {scene_name}")
            print(f"[DIR] Media directory: {media_dir}")
            print("=" * 60)

            # Determine temp files directory (ASSETS_DIR for render, PREVIEW_DIR for preview)
            temp_files_dir = PREVIEW_DIR if media_dir == PREVIEW_DIR else ASSETS_DIR

            # Ensure temp files directory exists
            try:
                os.makedirs(temp_files_dir, exist_ok=True)
            except Exception as e:
                print(f"[ERROR] Failed to create temp directory: {e}")

            # 1. Delete temp .py files from temp directory
            print(f"\n[STEP 1] Deleting temp .py files from {temp_files_dir}...")
            temp_deleted = 0
            if os.path.exists(temp_files_dir):
                for file in os.listdir(temp_files_dir):
                    if file.startswith('temp_') and file.endswith('.py'):
                        try:
                            temp_file = os.path.join(temp_files_dir, file)
                            os.remove(temp_file)
                            temp_deleted += 1
                            print(f"   [OK] Deleted: {file}")
                        except Exception as e:
                            print(f"   [ERROR] Error deleting {file}: {e}")
            print(f"   Deleted {temp_deleted} temp file(s)")

            # 2. Find rendered media files
            print("\n[STEP 2] Finding rendered media files...")

            # IMPORTANT: Manim creates folders based on the .py filename, NOT the scene name
            # Structure: media/videos/{python_filename_without_ext}/{quality}/SceneName.mp4
            # We need to search ALL folders in media/videos/ and media/images/

            videos_base = os.path.join(media_dir, 'videos')
            images_base = os.path.join(media_dir, 'images')

            print(f"   Videos base: {videos_base}")
            print(f"   Videos base exists: {os.path.exists(videos_base)}")
            print(f"   Images base: {images_base}")
            print(f"   Images base exists: {os.path.exists(images_base)}")

            final_path = None
            found_files = []  # List of dicts: {'path': path, 'size': size_mb}
            folders_to_delete = []

            # Process videos folder - search ALL subdirectories recursively
            if os.path.exists(videos_base):
                print(f"\n   [SCAN] Scanning ALL videos folders recursively...")

                # Walk through ALL subfolders
                for root, dirs, files in os.walk(videos_base):
                    # Track temp folders for deletion
                    if 'temp_' in root:
                        # Mark entire temp folder tree for deletion
                        parent_folder = root
                        while os.path.dirname(parent_folder) != videos_base:
                            parent_folder = os.path.dirname(parent_folder)
                        if parent_folder not in folders_to_delete:
                            folders_to_delete.append(parent_folder)

                    if files:
                        print(f"\n      [DIR] Checking: {root}")
                        print(f"      Found {len(files)} file(s)")

                        for file in files:
                            print(f"         - {file}")

                            if file.endswith(('.mp4', '.mov', '.webm', '.avi')):
                                source_file = os.path.join(root, file)
                                print(f"         [OK] Video file found!")
                                print(f"            Path: {source_file}")

                                # Verify file exists and has content
                                try:
                                    if os.path.exists(source_file):
                                        size_bytes = os.path.getsize(source_file)
                                        if size_bytes > 0:
                                            size_mb = size_bytes / (1024 * 1024)
                                            print(f"            Size: {size_mb:.2f} MB")

                                            # Store path AND size together
                                            found_files.append({
                                                'path': source_file,
                                                'size': size_mb,
                                                'name': file
                                            })

                                            # Set as final path (most recent video) - this will be returned for preview
                                            if not final_path:
                                                final_path = source_file
                                                print(f"            [FINAL] Set as preview path")
                                        else:
                                            print(f"            [WARNING] File is empty")
                                    else:
                                        print(f"            [WARNING] File doesn't exist")
                                except Exception as e:
                                    print(f"            [ERROR] Error checking file: {e}")
            else:
                print(f"   [WARNING] Videos base folder does not exist: {videos_base}")

            # Process images folder (for still frames/images) - search ALL subdirectories
            if os.path.exists(images_base):
                print(f"\n   [SCAN] Scanning ALL images folders recursively...")

                for root, dirs, files in os.walk(images_base):
                    # Track temp folders for deletion
                    if 'temp_' in root:
                        parent_folder = root
                        while os.path.dirname(parent_folder) != images_base:
                            parent_folder = os.path.dirname(parent_folder)
                        if parent_folder not in folders_to_delete:
                            folders_to_delete.append(parent_folder)

                    if files:
                        print(f"\n      [DIR] Checking: {root}")
                        print(f"      Found {len(files)} file(s)")

                        for file in files:
                            print(f"         - {file}")

                            if file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                source_file = os.path.join(root, file)
                                print(f"         [OK] Image file found!")
                                print(f"            Path: {source_file}")

                                # Verify file exists and has content
                                try:
                                    if os.path.exists(source_file):
                                        size_bytes = os.path.getsize(source_file)
                                        if size_bytes > 0:
                                            size_mb = size_bytes / (1024 * 1024)
                                            print(f"            Size: {size_mb:.2f} MB")

                                            # Store path AND size together
                                            found_files.append({
                                                'path': source_file,
                                                'size': size_mb,
                                                'name': file
                                            })

                                            # Set as final path if no video was found
                                            if not final_path:
                                                final_path = source_file
                                                print(f"            [FINAL] Set as preview path")
                                        else:
                                            print(f"            [WARNING] File is empty")
                                    else:
                                        print(f"            [WARNING] File doesn't exist")
                                except Exception as e:
                                    print(f"            [ERROR] Error checking file: {e}")
            else:
                print(f"   [WARNING] Images base folder does not exist: {images_base}")

            # 3. Do NOT delete temp folders yet - user needs to save first!
            # Temp folders will be cleaned up after successful save or at app shutdown
            print("\n[STEP 3] Temp folders preserved until after save...")
            if folders_to_delete:
                print(f"   Found {len(folders_to_delete)} temp folder(s) to clean later")
            else:
                print(f"   No temp folders found")

            print("\n" + "=" * 60)
            print(f"[OK] FILE SEARCH COMPLETE!")
            print(f"   Found {len(found_files)} rendered file(s)")

            # Show list of found files (using stored size data)
            if found_files:
                print(f"\n   Rendered files (in MEDIA_DIR):")
                for file_info in found_files:
                    filename = file_info['name']
                    size_mb = file_info['size']
                    print(f"      - {filename} ({size_mb:.2f} MB)")
                print(f"\n   [INFO] Files will remain in MEDIA_DIR until you save them")

            if final_path:
                print(f"\n   Preview path: {final_path}")
            else:
                print(f"\n   [WARNING] No output file found - check render logs above")
            print("=" * 60 + "\n")

            # Note: Temp folders are cleaned up after successful save,
            # or at app shutdown for unsaved renders (via cleanup_on_exit)

            return final_path

        except Exception as e:
            print(f"[ERROR] CLEANUP ERROR: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_rendered_file(self, source_path, suggested_name):
        """
        Show save dialog and move rendered file from assets to user's chosen location.

        Args:
            source_path: Path to the file in assets folder
            suggested_name: Suggested filename for save dialog

        Returns:
            dict with status and message
        """
        try:
            import shutil
            from datetime import datetime

            print("=" * 60)
            print(f"[SAVE] Showing save dialog...")
            print(f"   Source: {source_path}")
            print(f"   Suggested name: {suggested_name}")
            print("=" * 60)

            # Verify source file exists
            if not os.path.exists(source_path):
                print(f"[ERROR] Source file not found: {source_path}")
                return {
                    'status': 'error',
                    'message': 'Source file not found'
                }

            # Show save dialog
            result = app_state['window'].create_file_dialog(
                dialog_type=webview.SAVE_DIALOG,
                save_filename=suggested_name,
                file_types=('Video Files (*.mp4;*.mov;*.webm)', 'All Files (*.*)')
            )

            if not result:
                print("[INFO] User cancelled save dialog")
                # Don't delete file from assets - user might want to save later
                return {
                    'status': 'cancelled',
                    'message': 'Save cancelled by user'
                }

            # Get save path
            save_path = result[0] if isinstance(result, tuple) else result
            print(f"[OK] User chose: {save_path}")

            # Ensure file has proper extension
            if not save_path.endswith(('.mp4', '.mov', '.webm', '.avi')):
                save_path += '.mp4'

            # Copy file to user's location (use copy instead of move so we can clean up render folder properly)
            print(f"[INFO] Copying file...")
            print(f"   From: {source_path}")
            print(f"   To: {save_path}")

            shutil.copy2(source_path, save_path)

            print(f"[OK] File copied successfully!")

            # Check if source is from RENDER_DIR - if so, clear the entire render folder
            if source_path.startswith(RENDER_DIR):
                print(f"\n[INFO] Clearing render folder after save...")
                try:
                    clear_render_folder()
                    print(f"[OK] Render folder cleared")
                except Exception as e:
                    print(f"[ERROR] Failed to clear render folder: {e}")

                print("=" * 60)
            else:
                # For other locations (assets/media), clean up temp folders as before
                print(f"\n[INFO] Cleaning up temp folders...")
                videos_base = os.path.join(MEDIA_DIR, 'videos')
                images_base = os.path.join(MEDIA_DIR, 'images')
                folders_deleted = 0

                # Delete temp folders from videos
                if os.path.exists(videos_base):
                    for folder in os.listdir(videos_base):
                        if folder.startswith('temp_'):
                            folder_path = os.path.join(videos_base, folder)
                            try:
                                shutil.rmtree(folder_path)
                                folders_deleted += 1
                                print(f"   [OK] Deleted: {folder}")
                            except Exception as e:
                                print(f"   [ERROR] Failed to delete {folder}: {e}")

                # Delete temp folders from images
                if os.path.exists(images_base):
                    for folder in os.listdir(images_base):
                        if folder.startswith('temp_'):
                            folder_path = os.path.join(images_base, folder)
                            try:
                                shutil.rmtree(folder_path)
                                folders_deleted += 1
                                print(f"   [OK] Deleted: {folder}")
                            except Exception as e:
                                print(f"   [ERROR] Failed to delete {folder}: {e}")

                print(f"[OK] Cleaned up {folders_deleted} temp folder(s)")
                print("=" * 60)

            return {
                'status': 'success',
                'message': f'File saved to {save_path}',
                'path': save_path
            }

        except Exception as e:
            print(f"[ERROR] Save error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': str(e)
            }

    def get_settings(self):
        """Get application settings"""
        return app_state['settings']

    def update_settings(self, settings):
        """Update application settings"""
        app_state['settings'].update(settings)
        save_settings()
        return {'status': 'success', 'settings': app_state['settings']}

    def list_media_files(self):
        """List media files from assets directory only"""
        print("\n" + "="*60)
        print("[ASSETS] list_media_files() called")
        print("="*60)

        # Show files from ASSETS_DIR (not nested MEDIA_DIR folders)
        assets_dir = ASSETS_DIR
        print(f"[ASSETS] Looking in directory: {assets_dir}")
        print(f"[ASSETS] Directory exists: {os.path.exists(assets_dir)}")

        if not os.path.exists(assets_dir):
            print("[ASSETS] Creating assets directory...")
            os.makedirs(assets_dir)
            return {'files': []}

        files = []
        all_items = os.listdir(assets_dir)
        print(f"[ASSETS] Found {len(all_items)} items in directory:")
        for item in all_items:
            print(f"  - {item}")

        # Only list files directly in ASSETS_DIR (no subdirectories)
        for filename in os.listdir(assets_dir):
            file_path = os.path.join(assets_dir, filename)
            print(f"[ASSETS] Checking: {filename}")
            print(f"  - Is file: {os.path.isfile(file_path)}")

            # Include all asset types: videos, images, fonts, audio, subtitles
            # Skip temp .py files, .pyc, and hidden files
            if os.path.isfile(file_path) and not filename.startswith('.') and not filename.endswith(('.py', '.pyc')):
                # Supported extensions
                video_exts = ('.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.m4v')
                image_exts = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.bmp', '.webp', '.ico')
                font_exts = ('.ttf', '.otf', '.woff', '.woff2', '.ttc', '.eot')
                audio_exts = ('.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma')
                subtitle_exts = ('.srt', '.vtt', '.ass', '.ssa', '.sub')
                text_exts = ('.txt', '.md', '.json', '.xml', '.csv')

                if filename.lower().endswith(video_exts + image_exts + font_exts + audio_exts + subtitle_exts + text_exts):
                    file_info = {
                        'name': filename,
                        'path': file_path,
                        'size': os.path.getsize(file_path),
                        'mtime': os.path.getmtime(file_path)
                    }
                    files.append(file_info)
                    print(f"  [OK] Added to list: {filename} ({file_info['size']} bytes)")
                else:
                    print(f"  [SKIP] Unsupported file type: {filename}")
            else:
                if filename.startswith('.'):
                    print(f"  [SKIP] Hidden file: {filename}")
                elif filename.endswith(('.py', '.pyc')):
                    print(f"  [SKIP] Python file: {filename}")
                else:
                    print(f"  [SKIP] Not a file: {filename}")

        # Sort by modified time (newest first)
        files.sort(key=lambda x: x['mtime'], reverse=True)

        print(f"\n[ASSETS] Returning {len(files)} files")
        for f in files:
            print(f"  - {f['name']}")
        print("="*60 + "\n")

        return {'files': files}

    def open_media_folder(self):
        """Open the assets folder in file explorer"""
        try:
            # Open ASSETS_DIR instead of MEDIA_DIR
            assets_dir = ASSETS_DIR
            if not os.path.exists(assets_dir):
                os.makedirs(assets_dir)

            if sys.platform == 'win32':
                os.startfile(assets_dir)
            elif sys.platform == 'darwin':
                subprocess.run(['open', assets_dir])
            else:
                subprocess.run(['xdg-open', assets_dir])

            return {'status': 'success'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def play_media(self, file_path):
        """Play media file with system default player"""
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', file_path])
            else:
                subprocess.run(['xdg-open', file_path])

            return {'status': 'success'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def execute_command(self, command):
        """Execute a terminal command using persistent cmd.exe session"""
        try:
            print(f"Executing command: {command}")

            # Handle special install-venv command
            if command.strip().lower().startswith('install-venv'):
                parts = command.strip().split()
                if len(parts) >= 2:
                    response = parts[1].lower()
                    if response == 'yes':
                        # User confirmed - install venv
                        return self.install_venv()
                    elif response == 'no':
                        return {
                            'status': 'info',
                            'stdout': 'Installation skipped. You can run "install-venv yes" later to install.',
                            'stderr': '',
                            'returncode': 0
                        }
                    else:
                        return {
                            'status': 'error',
                            'stdout': '',
                            'stderr': 'Invalid response. Please type "install-venv yes" or "install-venv no"',
                            'returncode': 1
                        }
                else:
                    return {
                        'status': 'error',
                        'stdout': '',
                        'stderr': 'Usage: install-venv [yes/no]',
                        'returncode': 1
                    }

            # Handle pip install commands - redirect to venv pip
            if command.strip().lower().startswith('pip '):
                # Get venv pip executable
                if os.name == 'nt':
                    venv_pip = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
                else:
                    venv_pip = os.path.join(VENV_DIR, 'bin', 'pip')

                # Check if venv pip exists
                if not os.path.exists(venv_pip):
                    return {
                        'status': 'error',
                        'stdout': '',
                        'stderr': 'Virtual environment not found. Please set up the environment first.',
                        'returncode': 1
                    }

                # Replace 'pip' with venv pip path
                command_parts = command.strip().split(maxsplit=1)
                if len(command_parts) > 1:
                    new_command = f'"{venv_pip}" {command_parts[1]}'
                else:
                    new_command = f'"{venv_pip}"'

                print(f"Redirecting to venv pip: {new_command}")
                command = new_command

            # Use persistent cmd.exe session for all commands
            return self.send_terminal_command(command)

        except Exception as e:
            print(f"Error executing command: {e}")
            return {'status': 'error', 'message': str(e), 'stdout': '', 'stderr': '', 'returncode': 1}

    def start_persistent_terminal(self):
        """Start a persistent cmd.exe session using PTY (pywinpty) when available"""
        try:
            if app_state['terminal_process'] is not None:
                return {'status': 'info', 'message': 'Terminal already running'}

            print("[TERMINAL] Starting persistent cmd.exe session...")

            if WINPTY_AVAILABLE:
                print("[TERMINAL] Using pywinpty PTY for real terminal emulation")

                # Spawn cmd.exe with PTY
                terminal_process = winpty.PTY(80, 24)  # 80 columns, 24 rows
                terminal_process.spawn('cmd.exe')

                app_state['terminal_process'] = terminal_process
                app_state['terminal_output_buffer'] = []

                # Start background thread to read terminal output
                def read_terminal_output():
                    print("[TERMINAL PTY] Background reader thread started")
                    while True:
                        try:
                            # Read from PTY - this will block until data is available
                            # pywinpty.PTY.read() reads all available data
                            data = terminal_process.read()
                            if data:
                                app_state['terminal_output_buffer'].append(data)
                                # Uncomment to debug what's being received
                                # print(f"[TERMINAL PTY] Received {len(data)} bytes: {repr(data[-100:])}")
                        except Exception as e:
                            error_msg = str(e).lower()
                            # Ignore common non-error conditions
                            if "closed" not in error_msg and "timeout" not in error_msg and "no data" not in error_msg:
                                print(f"[TERMINAL PTY ERROR] {e}")
                            time.sleep(0.01)
                    print("[TERMINAL PTY] Background reader thread stopped")

                terminal_thread = threading.Thread(target=read_terminal_output, daemon=True)
                terminal_thread.start()
                app_state['terminal_thread'] = terminal_thread

                print("[TERMINAL PTY] Terminal started successfully")
                time.sleep(0.5)

                # Initialize terminal: cd to ASSETS_DIR and activate venv
                print(f"[TERMINAL PTY] Setting up initial environment...")

                # Change to assets directory
                terminal_process.write(f'cd /d "{ASSETS_DIR}"\r\n')
                time.sleep(0.3)

                # Activate virtual environment
                if os.name == 'nt':
                    activate_script = os.path.join(VENV_DIR, 'Scripts', 'activate.bat')
                else:
                    activate_script = os.path.join(VENV_DIR, 'bin', 'activate')

                if os.path.exists(activate_script):
                    terminal_process.write(f'call "{activate_script}"\r\n')
                    time.sleep(0.5)
                    print(f"[TERMINAL PTY] Activated venv at: {VENV_DIR}")
                else:
                    print(f"[TERMINAL PTY WARNING] Venv activate script not found: {activate_script}")

                # Wait for prompt to appear and clear screen
                time.sleep(0.5)

                # Clear the screen to hide initialization commands
                terminal_process.write('cls\r\n')
                time.sleep(0.2)

                # Clear the output buffer so initialization isn't shown to user
                app_state['terminal_output_buffer'] = []

                print("[TERMINAL PTY] Environment setup complete")
                return {'status': 'success', 'message': 'PTY terminal started'}

            else:
                # Fallback to subprocess.Popen
                print("[TERMINAL] Using fallback subprocess mode (no PTY)")

                terminal_process = subprocess.Popen(
                    ['cmd.exe'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=0,
                    env=get_clean_environment(),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )

                app_state['terminal_process'] = terminal_process
                app_state['terminal_output_buffer'] = []

                def read_terminal_output():
                    while terminal_process.poll() is None:
                        try:
                            line = terminal_process.stdout.readline()
                            if line:
                                app_state['terminal_output_buffer'].append(line)
                                print(f"[TERMINAL] {line.rstrip()}")
                        except Exception as e:
                            print(f"[TERMINAL ERROR] {e}")
                            break

                terminal_thread = threading.Thread(target=read_terminal_output, daemon=True)
                terminal_thread.start()
                app_state['terminal_thread'] = terminal_thread

                print("[TERMINAL] Terminal started successfully")
                time.sleep(0.5)

                # Initialize environment
                app_state['terminal_output_buffer'] = []
                terminal_process.stdin.write(f'cd /d "{ASSETS_DIR}"\n')
                terminal_process.stdin.flush()
                time.sleep(0.2)

                if os.name == 'nt':
                    activate_script = os.path.join(VENV_DIR, 'Scripts', 'activate.bat')
                else:
                    activate_script = os.path.join(VENV_DIR, 'bin', 'activate')

                if os.path.exists(activate_script):
                    terminal_process.stdin.write(f'call "{activate_script}"\n')
                    terminal_process.stdin.flush()
                    time.sleep(0.3)

                time.sleep(0.5)
                app_state['terminal_output_buffer'] = []
                return {'status': 'success', 'message': 'Fallback terminal started'}

        except Exception as e:
            print(f"[TERMINAL ERROR] Failed to start terminal: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def send_terminal_command(self, data):
        """Send data (raw input) to persistent terminal PTY"""
        try:
            if app_state['terminal_process'] is None:
                # Auto-start terminal if not running
                result = self.start_persistent_terminal()
                if result['status'] != 'success':
                    return result
                time.sleep(0.5)  # Wait for terminal to initialize

            terminal_process = app_state['terminal_process']

            # Check if using PTY mode or fallback mode
            if WINPTY_AVAILABLE and hasattr(terminal_process, 'write'):
                # PTY mode - send raw data
                terminal_process.write(data)
            else:
                # Fallback mode - use stdin
                terminal_process.stdin.write(data)
                terminal_process.stdin.flush()

            return {'status': 'success'}

        except Exception as e:
            print(f"[TERMINAL ERROR] {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def resize_terminal(self, cols, rows):
        """Resize the PTY terminal"""
        try:
            if app_state['terminal_process'] is None:
                return {'status': 'error', 'message': 'Terminal not running'}

            terminal_process = app_state['terminal_process']

            # Check if using PTY mode and has set_size method
            if WINPTY_AVAILABLE and hasattr(terminal_process, 'set_size'):
                print(f"[TERMINAL] Resizing PTY to {cols}x{rows}")
                terminal_process.set_size(cols, rows)
                return {'status': 'success'}
            else:
                # Fallback mode doesn't support resize
                return {'status': 'success', 'message': 'Resize not supported in fallback mode'}

        except Exception as e:
            print(f"[TERMINAL RESIZE ERROR] {e}")
            return {'status': 'error', 'message': str(e)}

    def get_terminal_output(self):
        """Get all terminal output (for continuous display)"""
        try:
            if app_state['terminal_process'] is None:
                print("[TERMINAL] Process not running, auto-starting...")
                # Auto-start terminal if not running
                self.start_persistent_terminal()
                time.sleep(0.5)  # Wait for initialization

            # Return all buffered output and clear buffer
            output = ''.join(app_state['terminal_output_buffer'])
            app_state['terminal_output_buffer'] = []

            # Only log when there's actual output (reduce spam)
            # if output:
            #     print(f"[TERMINAL] Returning {len(output)} bytes to frontend")

            return {
                'status': 'success',
                'output': output,
                'is_running': app_state['terminal_process'] is not None
            }

        except Exception as e:
            print(f"[TERMINAL ERROR] {e}")
            return {
                'status': 'error',
                'message': str(e),
                'output': '',
                'is_running': False
            }

    def check_claude_code_installed(self):
        """Check if Claude Code CLI is installed"""
        try:
            # Try to run claude --version
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5,
                env=get_clean_environment()
            )

            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"[CLAUDE CODE] Found: {version}")
                return {
                    'status': 'success',
                    'installed': True,
                    'version': version
                }
            else:
                return {
                    'status': 'success',
                    'installed': False,
                    'message': 'Claude Code not found'
                }

        except FileNotFoundError:
            print("[CLAUDE CODE] Not installed (command not found)")
            return {
                'status': 'success',
                'installed': False,
                'message': 'Claude Code not installed. Install with: npm install -g @anthropic-ai/claude-code'
            }
        except Exception as e:
            print(f"[CLAUDE CODE ERROR] {e}")
            return {
                'status': 'error',
                'message': str(e),
                'installed': False
            }

    def ai_edit_code(self, code, prompt):
        """Send code to Claude Code for AI editing"""
        try:
            # Check if Claude Code is installed
            check_result = self.check_claude_code_installed()
            if not check_result.get('installed', False):
                return {
                    'status': 'error',
                    'message': 'Claude Code not installed. Install it with: npm install -g @anthropic-ai/claude-code'
                }

            print(f"[AI EDIT] Sending code to Claude Code...")
            print(f"[AI EDIT] Prompt: {prompt}")

            # Create temporary file with code
            temp_file = os.path.join(PREVIEW_DIR, f'temp_ai_edit_{int(time.time())}.py')
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)

            # Use Claude Code to edit the file
            # Command: claude -p "prompt" --output-format text < file
            command = f'type "{temp_file}" | claude -p "{prompt}" --output-format text'

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,  # 60 second timeout for AI
                cwd=BASE_DIR,
                env=get_clean_environment()
            )

            # Clean up temp file
            try:
                os.remove(temp_file)
            except:
                pass

            if result.returncode == 0:
                edited_code = result.stdout.strip()
                print(f"[AI EDIT] Success! Received {len(edited_code)} characters")
                return {
                    'status': 'success',
                    'edited_code': edited_code,
                    'message': 'Code edited successfully by Claude Code'
                }
            else:
                error_msg = result.stderr or result.stdout or 'Unknown error'
                print(f"[AI EDIT ERROR] {error_msg}")
                return {
                    'status': 'error',
                    'message': f'Claude Code error: {error_msg}'
                }

        except subprocess.TimeoutExpired:
            return {
                'status': 'error',
                'message': 'Claude Code timed out after 60 seconds. Try a simpler prompt.'
            }
        except Exception as e:
            print(f"[AI EDIT ERROR] {e}")
            return {
                'status': 'error',
                'message': str(e)
            }

    def list_assets(self):
        """List all assets in the assets directory"""
        try:
            if not os.path.exists(ASSETS_DIR):
                os.makedirs(ASSETS_DIR, exist_ok=True)
                return {'directory': ASSETS_DIR, 'files': []}

            files = []
            previewable_ext = {'.mp4', '.mov', '.gif', '.png', '.jpg', '.jpeg', '.webp', '.webm'}

            for filename in os.listdir(ASSETS_DIR):
                if filename.startswith('temp_scene_'):
                    continue  # Skip temp files

                full_path = os.path.join(ASSETS_DIR, filename)

                if os.path.isfile(full_path):
                    try:
                        stat = os.stat(full_path)
                        ext = os.path.splitext(filename)[1].lower()
                        files.append({
                            'name': filename,
                            'path': full_path,
                            'size': stat.st_size,
                            'modified': stat.st_mtime,
                            'previewable': ext in previewable_ext
                        })
                    except:
                        continue

            files.sort(key=lambda x: x['modified'], reverse=True)
            return {'directory': ASSETS_DIR, 'files': files}

        except Exception as e:
            return {'directory': ASSETS_DIR, 'files': [], 'error': str(e)}

    def add_assets(self, file_paths):
        """Add assets by copying files to assets directory"""
        try:
            import shutil

            if not file_paths or not isinstance(file_paths, list):
                return {'status': 'error', 'message': 'No file paths provided'}

            os.makedirs(ASSETS_DIR, exist_ok=True)

            added = 0
            errors = []

            for src_path in file_paths:
                try:
                    if not os.path.exists(src_path):
                        errors.append(f'File not found: {src_path}')
                        continue

                    filename = os.path.basename(src_path)
                    dest_path = os.path.join(ASSETS_DIR, filename)

                    shutil.copy2(src_path, dest_path)
                    added += 1
                    print(f'[OK] Copied asset: {filename}')

                except Exception as e:
                    errors.append(f'Failed to copy {os.path.basename(src_path)}: {str(e)}')

            return {
                'status': 'success' if added > 0 else 'error',
                'added': added,
                'total': len(file_paths),
                'errors': errors if errors else None,
                'message': f'Added {added} file(s)' if added > 0 else 'Failed to add files'
            }

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_asset_as_data_url(self, file_path):
        """OPTIMIZED: Copy file to web/temp for faster HTTP serving (PyWebView blocks file:// URLs)"""
        try:
            import shutil
            import mimetypes

            if not os.path.exists(file_path):
                return {'status': 'error', 'message': 'File not found', 'dataUrl': None}

            # Create temp directory in web folder for HTTP serving
            web_temp_dir = os.path.join(BASE_DIR, 'web', 'temp_assets')
            os.makedirs(web_temp_dir, exist_ok=True)

            # Get filename and create temp copy
            filename = os.path.basename(file_path)
            temp_file = os.path.join(web_temp_dir, filename)

            # Copy file to web/temp_assets (fast for local files)
            if not os.path.exists(temp_file) or os.path.getmtime(file_path) > os.path.getmtime(temp_file):
                shutil.copy2(file_path, temp_file)

            # Return HTTP URL instead of data URL (much faster!)
            http_url = f'temp_assets/{filename}'

            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                ext = os.path.splitext(file_path)[1].lower()
                mime_types = {
                    # Videos
                    '.mp4': 'video/mp4',
                    '.mov': 'video/quicktime',
                    '.webm': 'video/webm',
                    '.avi': 'video/x-msvideo',
                    '.mkv': 'video/x-matroska',
                    '.flv': 'video/x-flv',
                    '.m4v': 'video/x-m4v',
                    # Images
                    '.gif': 'image/gif',
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.webp': 'image/webp',
                    '.svg': 'image/svg+xml',
                    '.bmp': 'image/bmp',
                    '.ico': 'image/x-icon',
                    # Audio
                    '.mp3': 'audio/mpeg',
                    '.wav': 'audio/wav',
                    '.ogg': 'audio/ogg',
                    '.m4a': 'audio/mp4',
                    '.aac': 'audio/aac',
                    '.flac': 'audio/flac',
                    '.wma': 'audio/x-ms-wma',
                    # Fonts
                    '.ttf': 'font/ttf',
                    '.otf': 'font/otf',
                    '.woff': 'font/woff',
                    '.woff2': 'font/woff2',
                    '.ttc': 'font/collection',
                    '.eot': 'application/vnd.ms-fontobject'
                }
                mime_type = mime_types.get(ext, 'application/octet-stream')

            return {
                'status': 'success',
                'dataUrl': http_url,  # Actually HTTP URL, not data URL (but keeping name for compatibility)
                'mimeType': mime_type,
                'size': os.path.getsize(file_path)
            }

        except Exception as e:
            print(f"Error preparing file for display: {e}")
            return {'status': 'error', 'message': str(e), 'dataUrl': None}

    def save_file_dialog(self, default_filename='output.mp4'):
        """Show save file dialog and return chosen path"""
        try:
            if app_state['window']:
                result = app_state['window'].create_file_dialog(
                    dialog_type=webview.SAVE_DIALOG,
                    save_filename=default_filename,
                    file_types=('Video Files (*.mp4;*.mov;*.gif;*.png)', 'All Files (*.*)')
                )

                if result and len(result) > 0:
                    return {'status': 'success', 'path': result[0]}
                else:
                    return {'status': 'cancelled', 'path': None}
            else:
                return {'status': 'error', 'message': 'Window not available'}
        except Exception as e:
            print(f"Error showing save dialog: {e}")
            return {'status': 'error', 'message': str(e)}

    def delete_asset(self, file_path):
        """Delete an asset file"""
        try:
            if not os.path.exists(file_path):
                return {'status': 'error', 'message': 'File not found'}

            os.remove(file_path)
            print(f"[OK] Deleted asset: {file_path}")
            return {'status': 'success', 'message': 'File deleted'}
        except Exception as e:
            print(f"Error deleting asset: {e}")
            return {'status': 'error', 'message': str(e)}

    def read_file_as_base64(self, file_path):
        """Read a file and return as base64 string (for image preview)"""
        try:
            import base64
            if not os.path.exists(file_path):
                raise Exception('File not found')

            with open(file_path, 'rb') as f:
                file_data = f.read()
                base64_data = base64.b64encode(file_data).decode('utf-8')
                return base64_data
        except Exception as e:
            print(f"[ERROR] Failed to read file as base64: {e}")
            raise Exception(f"Failed to read file: {str(e)}")

    def read_file_text(self, file_path):
        """Read text file content (for subtitle/text preview)"""
        try:
            if not os.path.exists(file_path):
                raise Exception('File not found')

            # Check if this is a binary file that shouldn't be read as text
            ext = os.path.splitext(file_path)[1].lower()
            binary_exts = ('.ttf', '.otf', '.woff', '.woff2', '.ttc', '.eot',
                          '.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma',
                          '.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.m4v',
                          '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico')
            if ext in binary_exts:
                raise Exception(f'Cannot read binary file as text: {ext}')

            # Try UTF-8 first (most common)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    return content
            except UnicodeDecodeError:
                pass

            # Try UTF-8 with BOM
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    return content
            except UnicodeDecodeError:
                pass

            # Try Windows default encoding (cp1252)
            try:
                with open(file_path, 'r', encoding='cp1252') as f:
                    content = f.read()
                    return content
            except UnicodeDecodeError:
                pass

            # Try latin-1 (accepts all bytes)
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
                    return content
            except Exception as e:
                print(f"[ERROR] Failed to read text file with all encodings: {e}")
                raise Exception(f"Failed to read file: Unable to decode with any encoding")

        except Exception as e:
            print(f"[ERROR] Failed to read text file: {e}")
            raise Exception(f"Failed to read file: {str(e)}")

    # Class-level variable for debouncing
    _last_fullscreen_call = 0
    _fullscreen_debounce_delay = 2.0  # 2 seconds

    def open_video_fullscreen(self, video_src):
        """Open video in a new PyWebView window"""
        try:
            import time

            # DEBOUNCE: Check if called too recently
            current_time = time.time()
            time_since_last = current_time - self.__class__._last_fullscreen_call

            if time_since_last < self.__class__._fullscreen_debounce_delay:
                print(f"[INFO] DEBOUNCED: Only {time_since_last:.2f}s since last call, ignoring...")
                return {
                    'status': 'debounced',
                    'message': 'Request debounced - too soon after previous call'
                }

            # Update last call time
            self.__class__._last_fullscreen_call = current_time

            print(f"[INFO] ========== open_video_fullscreen CALLED ==========")
            print(f"[INFO] Video source: {video_src}")

            # Extract the base URL from video source to get the HTTP server address
            # Example: http://127.0.0.1:30614/temp_assets/MyScene.mp4 -> http://127.0.0.1:30614
            if video_src.startswith('http://'):
                from urllib.parse import urlparse, quote
                parsed = urlparse(video_src)
                base_url = f"{parsed.scheme}://{parsed.netloc}"

                print(f"[INFO] Base URL: {base_url}")

                # Encode the video source for URL parameter
                encoded_src = quote(video_src, safe='')

                # Create fullscreen URL using the same HTTP server
                fullscreen_url = f"{base_url}/video_fullscreen.html?src={encoded_src}"

                print(f"[INFO] Fullscreen URL: {fullscreen_url}")
            else:
                raise Exception(f"Video source is not an HTTP URL: {video_src}")

            # Get screen dimensions
            try:
                import tkinter as tk
                root = tk.Tk()
                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()
                root.destroy()
            except:
                screen_width = 1920
                screen_height = 1080

            # Window size and position
            window_width = int(screen_width * 0.7)
            window_height = int(screen_height * 0.7)
            window_x = int(screen_width * 0.15)
            window_y = int(screen_height * 0.1)

            print(f"[INFO] Creating new PyWebView window...")
            print(f"[INFO] Window: {window_width}x{window_height} at ({window_x},{window_y})")

            # Create new PyWebView window
            # Since the GUI loop is already running, this window will appear immediately
            import webview
            new_window = webview.create_window(
                'Manim Studio - Video Player',
                fullscreen_url,
                width=window_width,
                height=window_height,
                resizable=True,
                x=window_x,
                y=window_y
            )

            print(f"[INFO] New PyWebView window created")
            print(f"[INFO] Total windows: {len(webview.windows)}")
            print(f"[INFO] ========== COMPLETE ==========")

            return {
                'status': 'success',
                'message': 'Video window opened'
            }

        except Exception as e:
            print(f"[ERROR] Failed to open video window: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'error',
                'message': str(e)
            }

    def get_setup_info(self):
        """Get setup information for virtual environment"""
        try:
            # Get Python version
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

            return {
                'status': 'success',
                'venv_path': VENV_DIR,
                'python_version': python_version
            }
        except Exception as e:
            print(f"[ERROR] Failed to get setup info: {e}")
            return {'status': 'error', 'message': str(e)}

    def check_manim_installed(self):
        """Check if Manim is installed in the virtual environment"""
        try:
            print("=" * 80)
            print("[INFO] check_manim_installed() CALLED")
            print(f"[INFO] Running as frozen EXE: {getattr(sys, 'frozen', False)}")
            print(f"[INFO] USER_DATA_DIR: {USER_DATA_DIR}")
            print(f"[INFO] VENV_DIR: {VENV_DIR}")

            # Get venv Python path
            if os.name == 'nt':
                venv_python = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
            else:
                venv_python = os.path.join(VENV_DIR, 'bin', 'python')

            print(f"[INFO] Expected venv Python path: {venv_python}")
            print(f"[INFO] Venv Python exists: {os.path.exists(venv_python)}")

            # Check if venv Python exists
            if not os.path.exists(venv_python):
                print(f"[WARNING] Virtual environment Python not found at: {venv_python}")
                print(f"[WARNING] Checking if VENV_DIR exists: {os.path.exists(VENV_DIR)}")
                if os.path.exists(VENV_DIR):
                    print(f"[INFO] VENV_DIR exists, listing contents:")
                    try:
                        contents = os.listdir(VENV_DIR)
                        print(f"[INFO] Contents: {contents[:10]}")  # First 10 items
                    except Exception as e:
                        print(f"[ERROR] Cannot list VENV_DIR: {e}")
                print("[INFO] Virtual environment may not be set up yet")
                return {
                    'status': 'success',
                    'installed': False,
                    'version': None,
                    'message': 'Virtual environment not set up'
                }

            print(f"[INFO] Using Python from virtual environment: {venv_python}")

            # Use pip show method directly (more reliable in EXE/MSIX)
            print("[INFO] Checking manim using 'pip show manim'...")
            env = get_clean_environment()
            if os.name == 'nt':
                venv_pip = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
            else:
                venv_pip = os.path.join(VENV_DIR, 'bin', 'pip')

            if not os.path.exists(venv_pip):
                print(f"[WARNING] Pip not found at: {venv_pip}")
                print("[INFO] Virtual environment may not be properly set up")
                print("=" * 80)
                result = {
                    'status': 'success',
                    'installed': False,
                    'version': None,
                    'message': 'Pip not found in virtual environment'
                }
                print(f"[INFO] check_manim_installed() RESULT: {result}")
                return result

            print(f"[INFO] Using pip from: {venv_pip}")
            result = subprocess.run(
                [venv_pip, 'show', 'manim'],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,  # Reduced timeout
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            print(f"[DEBUG] Pip show returncode: {result.returncode}")
            print(f"[DEBUG] Pip show stdout: {result.stdout[:200] if result.stdout else 'None'}")
            print(f"[DEBUG] Pip show stderr: {result.stderr[:200] if result.stderr else 'None'}")

            if result.returncode == 0 and result.stdout:
                version = None
                location = None
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        version = line.split(':', 1)[1].strip()
                    elif line.startswith('Location:'):
                        location = line.split(':', 1)[1].strip()

                print(f"[DEBUG] Parsed version from pip: {version}")
                print(f"[DEBUG] Parsed location from pip: {location}")

                if version:
                    print(f"[INFO] [OK] Manim is installed in venv: {version}")
                    if location:
                        print(f"[INFO] Location: {location}")
                    print("=" * 80)
                    pip_result = {
                        'status': 'success',
                        'installed': True,
                        'version': version,
                        'location': location
                    }
                    print(f"[INFO] check_manim_installed() RESULT: {pip_result}")
                    return pip_result

            # Not found
            print("[INFO] Manim is not installed in virtual environment")
            print("=" * 80)
            not_found_result = {
                'status': 'success',
                'installed': False,
                'version': None
            }
            print(f"[INFO] check_manim_installed() RESULT: {not_found_result}")
            return not_found_result

        except Exception as e:
            print(f"[ERROR] Failed to check Manim: {e}")
            import traceback
            traceback.print_exc()
            print("=" * 80)
            result = {
                'status': 'error',
                'installed': False,
                'message': str(e)
            }
            print(f"[ERROR] check_manim_installed() RESULT: {result}")
            return result

    def check_prerequisites(self):
        """Check if Python and LaTeX are installed and available"""
        try:
            results = {
                'python': {'installed': False, 'version': None, 'path': None},
                'latex': {'installed': False, 'variant': None, 'path': None}
            }

            # Check Python
            try:
                system_python = find_system_python()
                if system_python:
                    results['python']['installed'] = True
                    results['python']['path'] = system_python

                    # Get Python version
                    env = get_clean_environment()
                    version_result = subprocess.run(
                        [system_python, '--version'],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        env=env,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    version_output = (version_result.stdout + version_result.stderr).strip()
                    if 'python' in version_output.lower():
                        results['python']['version'] = version_output.replace('Python ', '')
            except Exception as e:
                print(f"[WARNING] Python check failed: {e}")

            # Check LaTeX (try multiple variants)
            latex_commands = [
                ('pdflatex', 'pdfLaTeX (MiKTeX)'),
                ('xelatex', 'XeLaTeX'),
                ('lualatex', 'LuaLaTeX'),
                ('latex', 'LaTeX')
            ]

            for cmd, variant_name in latex_commands:
                try:
                    env = get_clean_environment()
                    latex_result = subprocess.run(
                        [cmd, '--version'],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        env=env,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if latex_result.returncode == 0:
                        results['latex']['installed'] = True
                        results['latex']['variant'] = variant_name

                        # Try to get the full path
                        if os.name == 'nt':
                            where_result = subprocess.run(
                                ['where', cmd],
                                stdin=subprocess.DEVNULL,
                                capture_output=True,
                                text=True,
                                timeout=5,
                                env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW
                            )
                            if where_result.returncode == 0:
                                results['latex']['path'] = where_result.stdout.strip().split('\n')[0]
                        break
                except Exception as e:
                    continue

            return {
                'status': 'success',
                'results': results
            }

        except Exception as e:
            print(f"[ERROR] Failed to check prerequisites: {e}")
            return {'status': 'error', 'message': str(e)}

    def _escape_js_string(self, text):
        """Escape string for safe use in JavaScript evaluate_js calls"""
        if not text:
            return ""
        # Escape backslashes first, then quotes and newlines
        return text.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '')

    def install_environment(self, options):
        """
        Install virtual environment with selected packages.
        This method runs the installation in a background thread to prevent blocking the webview.
        """
        # Start installation in background thread to prevent exe from hanging
        def run_installation():
            self._do_install_environment(options)

        install_thread = threading.Thread(target=run_installation, daemon=True)
        install_thread.start()

        # Return immediately - updates will be sent via evaluate_js
        return {
            'status': 'started',
            'message': 'Installation started in background'
        }

    def _do_install_environment(self, options):
        """Internal method that performs the actual installation work"""
        global PYTHON_EXE

        try:
            optional_packages = options.get('optional_packages', [])
            custom_packages = options.get('custom_packages', [])

            print("[SETUP] Starting virtual environment installation...")

            # Update progress
            if app_state['window']:
                app_state['window'].evaluate_js('window.updateProgress(10, "[INFO] Initializing setup...")')

            # Find system Python
            system_python = find_system_python()
            if not system_python:
                raise Exception("Python not found. Please install Python 3.8+ and add it to PATH.")

            print(f"[SETUP] Using Python: {system_python}")

            # Create .manim_studio directory structure FIRST
            print("[SETUP] Creating .manim_studio directory structure...")
            if app_state['window']:
                app_state['window'].evaluate_js('window.updateProgress(15, "[INFO] Creating directory structure...")')

            # Create main .manim_studio directory
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            print(f"[SETUP] Created: {USER_DATA_DIR}")
            if app_state['window']:
                escaped_path = self._escape_js_string(USER_DATA_DIR)
                app_state['window'].evaluate_js(f'window.updateProgress(16, "[SUCCESS] Created: {escaped_path}")')

            # Create media subdirectory
            os.makedirs(MEDIA_DIR, exist_ok=True)
            print(f"[SETUP] Created: {MEDIA_DIR}")
            if app_state['window']:
                escaped_path = self._escape_js_string(MEDIA_DIR)
                app_state['window'].evaluate_js(f'window.updateProgress(17, "[SUCCESS] Created: {escaped_path}")')

            # Create assets subdirectory
            os.makedirs(ASSETS_DIR, exist_ok=True)
            print(f"[SETUP] Created: {ASSETS_DIR}")
            if app_state['window']:
                escaped_path = self._escape_js_string(ASSETS_DIR)
                app_state['window'].evaluate_js(f'window.updateProgress(18, "[SUCCESS] Created: {escaped_path}")')

            # Create venvs directory
            venvs_dir = os.path.dirname(VENV_DIR)
            os.makedirs(venvs_dir, exist_ok=True)
            print(f"[SETUP] Created: {venvs_dir}")
            if app_state['window']:
                escaped_path = self._escape_js_string(venvs_dir)
                app_state['window'].evaluate_js(f'window.updateProgress(19, "[SUCCESS] Created: {escaped_path}")')

            print("[SETUP] Directory structure created successfully!")

            # Create virtual environment
            if app_state['window']:
                app_state['window'].evaluate_js('window.updateProgress(20, "[INFO] Creating virtual environment...")')

            env = get_clean_environment()
            result = subprocess.run(
                [system_python, '-m', 'venv', VENV_DIR],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode != 0:
                raise Exception(f"Failed to create venv: {result.stderr}")

            print("[SETUP] Virtual environment created successfully")

            # Get venv Python path
            if os.name == 'nt':
                venv_python = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
                venv_pip = os.path.join(VENV_DIR, 'Scripts', 'pip.exe')
            else:
                venv_python = os.path.join(VENV_DIR, 'bin', 'python')
                venv_pip = os.path.join(VENV_DIR, 'bin', 'pip')

            PYTHON_EXE = venv_python

            # Upgrade pip
            if app_state['window']:
                app_state['window'].evaluate_js('window.updateProgress(30, "[INFO] Upgrading pip...")')

            subprocess.run(
                [venv_python, '-m', 'pip', 'install', '--upgrade', 'pip'],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Helper function to run pip with real-time output
            def run_pip_install(package, progress_value):
                """Run pip install with real-time output streaming"""
                if app_state['window']:
                    app_state['window'].evaluate_js(f'window.updateProgress({progress_value}, "[INFO] Installing {package}...")')

                print(f"[SETUP] Installing {package}...")

                # Use Popen for real-time output
                process = subprocess.Popen(
                    [venv_pip, 'install', package, '--verbose'],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',  # Force UTF-8 encoding
                    errors='replace',  # Replace invalid characters instead of crashing
                    env=env,
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )

                # Stream output line by line
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        # Send each line to UI console
                        escaped_line = self._escape_js_string(line)
                        if app_state['window']:
                            app_state['window'].evaluate_js(f'window.updateProgress({progress_value}, "{escaped_line}")')
                        print(f"  {line}")

                process.wait()

                if process.returncode != 0:
                    print(f"[WARNING] Failed to install {package}")
                    if app_state['window']:
                        app_state['window'].evaluate_js(f'window.updateProgress({progress_value}, "[WARNING] {package} installation had issues")')
                    return False
                else:
                    print(f"[SETUP] {package} installed successfully")
                    if app_state['window']:
                        app_state['window'].evaluate_js(f'window.updateProgress({progress_value}, "[SUCCESS] {package} installed successfully")')
                    return True

            # Install required packages
            required_packages = ['manim', 'manim-fonts', 'pywebview']
            progress = 40

            for pkg in required_packages:
                run_pip_install(pkg, progress)
                progress += 10

            # Install optional packages
            if optional_packages:
                for pkg in optional_packages:
                    run_pip_install(pkg, progress)
                    progress = min(progress + 5, 85)

            # Install custom packages
            if custom_packages:
                for pkg in custom_packages:
                    run_pip_install(pkg, progress)
                    progress = min(progress + 5, 90)

            # Final progress
            if app_state['window']:
                app_state['window'].evaluate_js('window.updateProgress(100, "[SUCCESS] Installation complete!")')

            print("[SETUP] Installation complete!")

            # Notify UI that installation is complete
            if app_state['window']:
                app_state['window'].evaluate_js('window.onInstallationComplete(true, "Installation successful")')

        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] Installation failed: {error_msg}")
            if app_state['window']:
                escaped_error = self._escape_js_string(f"[ERROR] Installation failed: {error_msg}")
                app_state['window'].evaluate_js(f'window.updateProgress(0, "{escaped_error}")')
                # Notify UI that installation failed
                app_state['window'].evaluate_js(f'window.onInstallationComplete(false, "{escaped_error}")')

    def open_folder(self, folder_path):
        """Open folder in file explorer"""
        try:
            if not folder_path or not os.path.exists(folder_path):
                return {'status': 'error', 'message': 'Folder does not exist'}

            if sys.platform == 'win32':
                os.startfile(folder_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', folder_path])
            else:
                subprocess.run(['xdg-open', folder_path])

            return {'status': 'success'}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def select_folder(self):
        """Show folder selection dialog"""
        try:
            if app_state['window']:
                result = app_state['window'].create_file_dialog(
                    webview.FOLDER_DIALOG,
                    directory=os.path.expanduser('~')
                )

                if result and len(result) > 0:
                    return {'status': 'success', 'path': result[0]}
                else:
                    return {'status': 'cancelled', 'path': None}
            else:
                return {'status': 'error', 'message': 'Window not available'}

        except Exception as e:
            print(f"Error selecting folder: {e}")
            return {'status': 'error', 'message': str(e)}

    def select_files_to_upload(self):
        """Show file selection dialog for uploading assets"""
        try:
            if app_state['window']:
                result = app_state['window'].create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=(
                        'All Assets (*.mp4;*.mov;*.avi;*.webm;*.mkv;*.png;*.jpg;*.jpeg;*.gif;*.svg;*.bmp;*.webp;*.ttf;*.otf;*.woff;*.woff2;*.ttc;*.mp3;*.wav;*.ogg;*.m4a;*.aac;*.flac;*.srt;*.vtt;*.ass;*.txt;*.md;*.json)',
                        'Video Files (*.mp4;*.mov;*.avi;*.webm;*.mkv;*.flv;*.m4v)',
                        'Image Files (*.png;*.jpg;*.jpeg;*.gif;*.svg;*.bmp;*.webp;*.ico)',
                        'Font Files (*.ttf;*.otf;*.woff;*.woff2;*.ttc;*.eot)',
                        'Audio Files (*.mp3;*.wav;*.ogg;*.m4a;*.aac;*.flac;*.wma)',
                        'Subtitle Files (*.srt;*.vtt;*.ass;*.ssa;*.sub)',
                        'Text Files (*.txt;*.md;*.json;*.xml;*.csv)',
                        'All Files (*.*)'
                    )
                )

                if result and len(result) > 0:
                    print(f'[UPLOAD] User selected {len(result)} file(s):')
                    for f in result:
                        print(f'  - {f}')
                    return {'status': 'success', 'file_paths': result}
                else:
                    print('[UPLOAD] User cancelled file selection')
                    return {'status': 'cancelled', 'file_paths': []}
            else:
                return {'status': 'error', 'message': 'Window not available'}

        except Exception as e:
            print(f"[UPLOAD] Error selecting files: {e}")
            return {'status': 'error', 'message': str(e)}

    def save_app_settings(self, settings):
        """Save app settings to .manim_studio/settings.json"""
        try:
            import json
            settings_file = os.path.join(USER_DATA_DIR, 'settings.json')

            # Ensure user data directory exists
            os.makedirs(USER_DATA_DIR, exist_ok=True)

            # Save settings to file
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)

            print(f"[SETTINGS] Saved settings to {settings_file}")
            return {'status': 'success', 'message': 'Settings saved successfully'}

        except Exception as e:
            print(f"Error saving settings: {e}")
            return {'status': 'error', 'message': str(e)}

    def load_app_settings(self):
        """Load app settings from .manim_studio/settings.json"""
        try:
            import json
            settings_file = os.path.join(USER_DATA_DIR, 'settings.json')

            # Check if settings file exists
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                print(f"[SETTINGS] Loaded settings from {settings_file}")
                return {'status': 'success', 'settings': settings}
            else:
                # Return default settings
                default_settings = {
                    'defaultSaveLocation': '',
                    'renderQuality': '1080p',
                    'fps': 60,
                    'autoSave': True,
                    'autoOpenOutput': False,
                    'theme': 'dark'
                }
                print("[SETTINGS] No settings file found, using defaults")
                return {'status': 'success', 'settings': default_settings}

        except Exception as e:
            print(f"Error loading settings: {e}")
            return {'status': 'error', 'message': str(e), 'settings': {}}

    def get_system_info(self):
        """Get system information and Python environment details"""
        import platform

        print("=" * 80)
        print("[SYSTEM INFO] get_system_info() CALLED")
        print(f"[SYSTEM INFO] Running as frozen EXE: {getattr(sys, 'frozen', False)}")
        print(f"[SYSTEM INFO] USER_DATA_DIR: {USER_DATA_DIR}")
        print(f"[SYSTEM INFO] VENV_DIR: {VENV_DIR}")

        # Get actual Python executable being used for manim operations
        # IMPORTANT: This should show the Python used for MANIM, not the Python running this app
        global PYTHON_EXE

        print("[SYSTEM INFO] Determining Python executable for manim operations...")

        # Determine venv Python path
        if os.name == 'nt':
            venv_python = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
        else:
            venv_python = os.path.join(VENV_DIR, 'bin', 'python')

        print(f"[SYSTEM INFO] Expected venv Python: {venv_python}")
        print(f"[SYSTEM INFO] Venv Python exists: {os.path.exists(venv_python)}")

        # Check what Python will be used for manim operations
        if os.path.exists(venv_python):
            # Venv exists - this is what will be used for manim
            actual_python = venv_python
            python_source = f".manim_studio venv (used for manim)"
            print(f"[SYSTEM INFO] Found .manim_studio venv: {actual_python}")
        elif PYTHON_EXE:
            # PYTHON_EXE is cached - this is what will be used
            actual_python = PYTHON_EXE
            python_source = "System Python (used for manim)"
            print(f"[SYSTEM INFO] Using cached system Python: {actual_python}")
        else:
            # Need to find system Python
            actual_python = find_system_python()
            if actual_python:
                python_source = "System Python (used for manim)"
                print(f"[SYSTEM INFO] Found system Python: {actual_python}")
            else:
                actual_python = "ERROR: No Python found! Install Python to use this app."
                python_source = "not found"
                print(f"[SYSTEM INFO] ERROR: No Python found!")

        # Get Python version from the actual Python that will be used
        try:
            if actual_python and os.path.exists(actual_python):
                result = subprocess.run(
                    [actual_python, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=get_clean_environment()
                )
                python_version = (result.stdout + result.stderr).strip()
            else:
                python_version = "Unknown - Python not found"
        except:
            python_version = sys.version if not getattr(sys, 'frozen', False) else "Unable to determine"

        info = {
            'python_version': python_version,
            'python_exe': actual_python,
            'python_source': python_source,
            'platform': platform.platform(),
            'processor': platform.processor(),
            'base_dir': BASE_DIR,
            'media_dir': app_state['output_dir'],
            'assets_dir': ASSETS_DIR,
            'venv_path': VENV_DIR,
            'venv_exists': os.path.exists(venv_python)
        }

        # Check Manim using the working check_manim_installed() method
        # This uses 'pip show manim' which is reliable in EXE/MSIX
        print("[SYSTEM INFO] Checking manim using check_manim_installed()...")
        try:
            manim_check = self.check_manim_installed()
            if manim_check.get('installed'):
                version = manim_check.get('version', 'Unknown')
                info['manim_version'] = f'Manim Community v{version}'
                info['manim_installed'] = True
                print(f"[SYSTEM INFO] [OK] Manim detected: v{version}")
            else:
                info['manim_version'] = 'Not installed'
                info['manim_installed'] = False
                message = manim_check.get('message', 'Unknown reason')
                print(f"[SYSTEM INFO] Manim not installed: {message}")
        except Exception as e:
            print(f"[SYSTEM INFO] Error checking manim: {e}")
            import traceback
            traceback.print_exc()
            info['manim_version'] = 'Not installed'
            info['manim_installed'] = False
            print(f"[SYSTEM INFO] Setting manim_installed=False due to exception")

        # Check for essential Python libraries using the actual Python
        try:
            if actual_python and os.path.exists(actual_python):
                result = subprocess.run(
                    [actual_python, '-m', 'pip', 'list', '--format=json'],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=get_clean_environment()
                )
                if result.returncode == 0:
                    packages = json.loads(result.stdout)
                    info['installed_packages'] = packages
                    info['packages_count'] = len(packages)

                    # Check for essential packages
                    package_names = [pkg['name'].lower() for pkg in packages]
                    essential_packages = ['manim', 'numpy', 'pillow', 'opencv-python']
                    missing_packages = [pkg for pkg in essential_packages if pkg not in package_names]

                    info['missing_packages'] = missing_packages
                    info['essential_packages_installed'] = len(missing_packages) == 0
                else:
                    info['packages_count'] = 0
                    info['installed_packages'] = []
                    info['packages_error'] = 'Failed to list packages'
            else:
                info['packages_count'] = 0
                info['installed_packages'] = []
                info['packages_error'] = 'Python not available'

        except Exception as e:
            print(f'Error checking Python packages: {e}')
            info['packages_count'] = 0
            info['installed_packages'] = []

        print("=" * 80)
        print(f"[SYSTEM INFO] get_system_info() RETURNING:")
        print(f"[SYSTEM INFO]   manim_installed: {info.get('manim_installed', 'NOT SET')}")
        print(f"[SYSTEM INFO]   manim_version: {info.get('manim_version', 'NOT SET')}")
        print("=" * 80)
        return info

    def install_venv(self):
        """Install virtual environment - called by user confirmation"""
        result = setup_venv(window=app_state['window'])
        if result:
            return {'status': 'success', 'message': 'Virtual environment installed successfully', 'returncode': 0, 'stdout': 'Installation complete', 'stderr': ''}
        else:
            return {'status': 'error', 'message': 'Failed to install virtual environment', 'returncode': 1, 'stdout': '', 'stderr': 'Installation failed'}

    # AI/LLM code completion removed

    def get_video_files(self):
        """Get list of all video files from media directory"""
        try:
            video_files = []
            media_path = MEDIA_DIR

            if not os.path.exists(media_path):
                return {'status': 'success', 'videos': []}

            # Supported video extensions
            video_extensions = ('.mp4', '.mov', '.avi', '.webm', '.mkv', '.flv', '.m4v')

            for root, dirs, files in os.walk(media_path):
                for file in files:
                    if file.lower().endswith(video_extensions):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, media_path)

                        # Get video duration using ffprobe if available
                        try:
                            duration = self._get_video_duration(full_path)
                        except:
                            duration = 0

                        video_files.append({
                            'name': file,
                            'path': full_path,
                            'relative_path': rel_path,
                            'duration': duration
                        })

            # Sort by modification time (newest first)
            video_files.sort(key=lambda x: os.path.getmtime(x['path']), reverse=True)

            return {'status': 'success', 'videos': video_files}

        except Exception as e:
            print(f"[VIDEO LIST ERROR] {e}")
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def _get_video_duration(self, video_path):
        """Get video duration in seconds using ffprobe"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            return 0
        except:
            return 0

    def trim_video(self, video_path, start_time, end_time, output_name):
        """Trim video using FFmpeg"""
        try:
            # Validate inputs
            if not os.path.exists(video_path):
                return {'status': 'error', 'message': 'Video file not found'}

            if not output_name:
                output_name = f"trimmed_{os.path.basename(video_path)}"

            # Ensure output has .mp4 extension
            if not output_name.lower().endswith('.mp4'):
                output_name += '.mp4'

            output_path = os.path.join(MEDIA_DIR, output_name)

            # Build FFmpeg command
            cmd = ['ffmpeg', '-i', video_path, '-y']  # -y to overwrite

            # Add start time if specified
            if start_time > 0:
                cmd.extend(['-ss', str(start_time)])

            # Add duration/end time if specified
            if end_time > 0:
                if start_time > 0:
                    duration = end_time - start_time
                    cmd.extend(['-t', str(duration)])
                else:
                    cmd.extend(['-to', str(end_time)])

            # Copy codec for fast processing (no re-encoding)
            cmd.extend(['-c', 'copy', output_path])

            print(f"[TRIM VIDEO] Running command: {' '.join(cmd)}")

            # Run FFmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': f'Video trimmed successfully: {output_name}',
                    'output_path': output_path
                }
            else:
                return {
                    'status': 'error',
                    'message': f'FFmpeg error: {result.stderr}'
                }

        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': 'Video trimming timed out'}
        except FileNotFoundError:
            return {'status': 'error', 'message': 'FFmpeg not found. Please install FFmpeg.'}
        except Exception as e:
            print(f"[TRIM VIDEO ERROR] {e}")
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def combine_videos(self, video_paths, output_name):
        """Combine multiple videos using FFmpeg"""
        try:
            # Validate inputs
            if not video_paths or len(video_paths) < 2:
                return {'status': 'error', 'message': 'Please select at least 2 videos to combine'}

            # Validate all paths exist
            for path in video_paths:
                if not os.path.exists(path):
                    return {'status': 'error', 'message': f'Video file not found: {os.path.basename(path)}'}

            if not output_name:
                output_name = f"combined_{int(time.time())}.mp4"

            # Ensure output has .mp4 extension
            if not output_name.lower().endswith('.mp4'):
                output_name += '.mp4'

            output_path = os.path.join(MEDIA_DIR, output_name)

            # Create concat file list
            concat_file = os.path.join(MEDIA_DIR, f'concat_list_{int(time.time())}.txt')

            with open(concat_file, 'w', encoding='utf-8') as f:
                for video_path in video_paths:
                    # FFmpeg concat requires absolute paths with forward slashes
                    abs_path = os.path.abspath(video_path).replace('\\', '/')
                    f.write(f"file '{abs_path}'\n")

            # Build FFmpeg command for concatenation
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',  # Copy codec for fast processing
                '-y',  # Overwrite output file
                output_path
            ]

            print(f"[COMBINE VIDEOS] Running command: {' '.join(cmd)}")

            # Run FFmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            # Clean up concat file
            try:
                os.remove(concat_file)
            except:
                pass

            if result.returncode == 0:
                return {
                    'status': 'success',
                    'message': f'Videos combined successfully: {output_name}',
                    'output_path': output_path
                }
            else:
                return {
                    'status': 'error',
                    'message': f'FFmpeg error: {result.stderr}'
                }

        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': 'Video combining timed out'}
        except FileNotFoundError:
            return {'status': 'error', 'message': 'FFmpeg not found. Please install FFmpeg.'}
        except Exception as e:
            print(f"[COMBINE VIDEOS ERROR] {e}")
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}


def find_free_port():
    """Find a free port on localhost"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def check_venv_exists():
    """Check if virtual environment exists"""
    if os.name == 'nt':
        venv_python = os.path.join(VENV_DIR, 'Scripts', 'python.exe')
    else:
        venv_python = os.path.join(VENV_DIR, 'bin', 'python')

    return os.path.exists(venv_python)


def start_app():
    """Start the desktop application"""
    # Load settings
    load_settings()

    # Create required directories
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    # Check if virtual environment exists
    venv_exists = check_venv_exists()

    print("=" * 60)
    if venv_exists:
        print("[OK] Virtual environment found")
        print(f"[OK] Location: {VENV_DIR}")
    else:
        print("[INFO] Virtual environment not found")
        print("[INFO] Will launch setup wizard")
    print("=" * 60)

    # Start Pyright LSP bridge for VSCode-quality IntelliSense
    def start_lsp_bridge():
        """Start the LSP bridge in background"""
        import threading
        import time

        def run_lsp():
            try:
                # Check if lsp_venv exists
                lsp_venv_path = os.path.join(BASE_DIR, 'lsp_venv')
                if os.name == 'nt':
                    python_path = os.path.join(lsp_venv_path, 'Scripts', 'python.exe')
                else:
                    python_path = os.path.join(lsp_venv_path, 'bin', 'python')

                lsp_bridge_path = os.path.join(BASE_DIR, 'lsp_bridge.py')

                if not os.path.exists(python_path) or not os.path.exists(lsp_bridge_path):
                    print('[LSP] LSP environment or bridge not found, skipping IntelliSense startup')
                    return

                print('[LSP] Starting Pyright Language Server on port 8765...')

                # Start LSP bridge process
                env = get_clean_environment()
                process = subprocess.Popen(
                    [python_path, lsp_bridge_path, '8765', lsp_venv_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',  # Force UTF-8 encoding
                    errors='replace',  # Replace invalid characters instead of crashing
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )

                # Store process for cleanup
                app_state['lsp_process'] = process

                print('[LSP] [OK] Pyright Language Server started')

            except Exception as e:
                print(f'[LSP] Failed to start LSP bridge: {e}')

        # Start in background thread
        threading.Thread(target=run_lsp, daemon=True).start()

    # LSP bridge disabled - using basic Monaco editor without LSP
    # start_lsp_bridge()

    # Create API instance
    api = ManimAPI()

    # Choose HTML file based on venv existence
    if venv_exists:
        html_path = os.path.join(BASE_DIR, 'web', 'index.html')
        window_title = 'Manim Studio - Professional Edition'
    else:
        html_path = os.path.join(BASE_DIR, 'web', 'setup.html')
        window_title = 'Manim Studio - Virtual Environment Setup'

    # Create native desktop window
    window = webview.create_window(
        title=window_title,
        url=html_path,
        js_api=api,
        width=1600,
        height=1000,
        resizable=True,
        frameless=False,
        easy_drag=False,
        min_size=(1200, 800)
    )

    # Store window reference
    app_state['window'] = window

    # Start the application (debug enabled for development)
    webview.start(debug=False)
    #webview.start(debug=True)



def cleanup_on_exit():
    """Clean up unsaved temp folders and preview files"""
    print("\n[CLEANUP] App is closing, cleaning up...")

    import shutil

    # Clean up preview MP4 files that were copied to assets folder
    print("[CLEANUP] Cleaning up preview files from assets folder...")
    preview_cleanup_count = 0
    if app_state['preview_files_to_cleanup']:
        for preview_file in app_state['preview_files_to_cleanup']:
            try:
                if os.path.exists(preview_file):
                    os.remove(preview_file)
                    preview_cleanup_count += 1
                    print(f"  Removed preview file: {os.path.basename(preview_file)}")
            except Exception as e:
                print(f"  Error removing preview file {os.path.basename(preview_file)}: {e}")

        if preview_cleanup_count > 0:
            print(f"[OK] Cleaned up {preview_cleanup_count} preview file(s) from assets")
        else:
            print("[OK] No preview files to clean from assets")
    else:
        print("[OK] No preview files to clean")

    # Clean up temp folders in MEDIA_DIR (only if user didn't save)
    print("[CLEANUP] Cleaning up unsaved temp folders...")
    cleanup_count = 0

    # Check videos folder for temp_ folders
    videos_base = os.path.join(MEDIA_DIR, 'videos')
    if os.path.exists(videos_base):
        try:
            for folder_name in os.listdir(videos_base):
                folder_path = os.path.join(videos_base, folder_name)
                if os.path.isdir(folder_path) and folder_name.startswith('temp_'):
                    shutil.rmtree(folder_path)
                    cleanup_count += 1
                    print(f"  Removed temp folder: {folder_name}")
        except Exception as e:
            print(f"  Error cleaning videos temp folders: {e}")

    # Check images folder for temp_ folders
    images_base = os.path.join(MEDIA_DIR, 'images')
    if os.path.exists(images_base):
        try:
            for folder_name in os.listdir(images_base):
                folder_path = os.path.join(images_base, folder_name)
                if os.path.isdir(folder_path) and folder_name.startswith('temp_'):
                    shutil.rmtree(folder_path)
                    cleanup_count += 1
                    print(f"  Removed temp folder: {folder_name}")
        except Exception as e:
            print(f"  Error cleaning images temp folders: {e}")

    if cleanup_count > 0:
        print(f"[OK] Cleaned up {cleanup_count} temp folder(s)")
    else:
        print("[OK] No temp folders to clean")
    print("[OK] Cleanup complete")

if __name__ == '__main__':
    import atexit
    atexit.register(cleanup_on_exit)

    print("=" * 60)
    print("Starting Manim Studio Desktop App...")
    print("=" * 60)
    print(f"Base Directory: {BASE_DIR}")
    print(f"User Data: {USER_DATA_DIR}")
    print(f"Media Directory: {MEDIA_DIR}")
    print(f"Assets Directory: {ASSETS_DIR}")
    print(f"Preview Directory: {PREVIEW_DIR}")
    print("=" * 60)
    start_app()
