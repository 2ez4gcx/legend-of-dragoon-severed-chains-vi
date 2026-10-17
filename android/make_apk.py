"""Dựng APK Android (arm64-v8a) của bản Việt hoá The Legend of Dragoon chạy trên Severed Chains — không cần Gradle.

Cách gọi:
    python android/make_apk.py --version 0.2 [--build 1] [--zip release/LoD-SC-VN-v0.2-sc-affcef0-windows.zip]
Cần chạy trước: android/build_natives.ps1 (thư viện native), android/build_sc_android.ps1 (sc-android.jar + shader ES),
và có: deps/android/jre/jre25-android-arm64.tar.xz (JRE 25 Android của AngelAuraMC, kiểm SHA-256 bên dưới),
deps/android/maven/{ffmpeg-8.0.1-1.5.13,javacpp-1.5.13}-android-arm64.jar (Maven Central), Android SDK build-tools 36.1.0
+ platforms/android-36, JDK 17 (javac/d8/apksigner).

Nội dung APK:
    lib/arm64-v8a/*.so      SDL3, OpenAL Soft, Opus, LWJGL (core/opengles/stb), libsclauncher, FFmpeg+JavaCPP (bytedeco)
                            — không nén, căn 16 KB (zipalign -P 16), nạp thẳng từ APK (extractNativeLibs=false)
    classes.dex             vn.lodsc.* (SetupActivity, VnGameActivity, TouchPad, Payload) + lớp Java của SDL3
    assets/payload.zip      (không nén lại) jre/ = JRE 25; game/ = gói Windows đã phát hành bỏ phần chỉ dùng cho Windows
                            (launch*.bat, launch.conf, updater.jar, natives Windows/Linux, FFmpeg Windows) + vi/sc-android.jar
                            + gfx/shaders_es + android-classpath.txt + vi/NGUON/android (mã nguồn phần Android, AGPL)
    assets/payload.version  SHA-256 của payload.zip (Payload.java giải nén lại khi khác)
Ký bằng khoá deps/android/keys/lodsc-release.jks (tạo lần đầu, mật khẩu ngẫu nhiên trong keystore.pass — SAO LƯU, mọi bản
cập nhật phải ký cùng khoá). Kết quả: release/LoD-SC-VN-v<ver>-android-arm64.apk (+ dòng trong release/SHA256SUMS.txt).
Xác định: cùng đầu vào -> cùng payload.zip (thời gian cố định, thứ tự cố định).
"""
import argparse
import hashlib
import io
import lzma
import os
import posixpath
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
AND = os.path.join(ROOT, 'android')
DEPS = os.path.join(ROOT, 'deps', 'android')
# Python cài dạng gói (MSIX) không đọc được %LOCALAPPDATA%\Android\Sdk -> dùng bản chép build-tools 36.1.0 + android.jar
# trong deps/android/sdk-tools (hoặc ANDROID_HOME)
SDK = os.environ.get('ANDROID_HOME', os.path.join(DEPS, 'sdk-tools'))
BT = os.path.join(SDK, 'build-tools', '36.1.0')
ANDROID_JAR = os.path.join(SDK, 'platforms', 'android-36', 'android.jar')
JDK17 = os.environ.get('JDK17', r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot')
# ABI -> (tên trong tệp JRE/bytedeco, SHA-256 JRE = digest GitHub của bản AngelAuraMC). x86_64 chỉ để thử trên giả lập.
ABIS = {
    'arm64-v8a': ('arm64', 'd3eb7afe2240c26728a1bb440502c5f18ac3883e932d202dd7f0c9bcbbce4c37'),
    'x86_64': ('x86_64', '7fca862ee1b2d5fe23cd9c9c3d9b7ad3c241947ad1a6cc9464ef2e674867105d'),
}
MAVEN = os.path.join(DEPS, 'maven')
SDL_JAVA = os.path.join(DEPS, 'out', 'sdl-java')
PKG = 'Severed Chains (VN)/'
FIXED = (2026, 10, 17, 0, 0, 0)
# Tệp của gói Windows không đưa vào bản Android
DROP_TOP = re.compile(r'^(launch[^/]*\.(bat|sh|command)|launch\.conf|updater\.jar|HUONG_DAN_VIET_HOA\.txt)$')
DROP_LIB = re.compile(r'natives-(windows|linux|macos)|-windows-x86_64\.jar$')
NATIVE_LIBS = ['libSDL3.so', 'libopenal.so', 'libopus.so', 'liblwjgl.so', 'liblwjgl_opengles.so', 'liblwjgl_stb.so',
               'libsclauncher.so']


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(*cmd, **kw):
    r = subprocess.run(list(cmd), capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    if r.returncode:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        sys.exit('LOI: %s' % ' '.join(os.path.basename(str(c)) for c in cmd[:2]))
    return r.stdout


def classpath(launch_bat):
    """thứ tự classpath của launch.bat (-cp "a.jar;libs/b.jar;...") bỏ jar chỉ dùng cho Windows"""
    m = re.search(r'-cp "([^"]+)"', launch_bat)
    if not m:
        sys.exit('LOI: khong doc duoc classpath trong launch.bat')
    out = []
    for p in m.group(1).split(';'):
        p = p.strip().replace('\\', '/')
        if p and not DROP_LIB.search(p):
            out.append(p)
    return out


def payload(zip_path, version, abi):
    entries = []   # (tên, bytes)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        launch = z.read(PKG + 'launch.bat').decode('utf-8')
        for n in names:
            if not n.startswith(PKG) or n.endswith('/'):
                continue
            rel = n[len(PKG):]
            if DROP_TOP.match(rel) or (rel.startswith('libs/') and DROP_LIB.search(rel)):
                continue
            entries.append(('game/' + rel, z.read(n)))
    cp = ['vi/sc-android.jar', 'vi/sc-vi.jar'] + classpath(launch)
    present = {e[0][len('game/'):] for e in entries}
    missing = [p for p in cp if p not in present and p != 'vi/sc-android.jar']
    if missing:
        sys.exit('LOI: classpath thieu %s' % missing)
    entries.append(('game/android-classpath.txt', ('\n'.join(cp) + '\n').encode()))
    entries.append(('game/vi/sc-android.jar', open(os.path.join(ROOT, 'out', 'android', 'sc-android.jar'), 'rb').read()))
    es = os.path.join(ROOT, 'out', 'android', 'shaders_es')
    for f in sorted(os.listdir(es)):
        entries.append(('game/gfx/shaders_es/' + f, open(os.path.join(es, f), 'rb').read()))
    # mã nguồn phần Android (AGPL-3.0 như SC): app Java, launcher C, lớp đè SC, script dựng
    for base, _, files in os.walk(AND):
        for f in sorted(files):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, AND).replace('\\', '/')
            if rel.startswith(('app/res/mipmap')) or f.endswith('.pyc'):
                continue
            entries.append(('game/vi/NGUON/android/' + rel, open(p, 'rb').read()))
    entries.append(('game/vi/VERSION-android.txt', ('viet_hoa=%s\nandroid=1\nlod_sc_commit=%s\n' % (
        version, run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip())).encode()))

    jre_txz = os.path.join(DEPS, 'jre', 'jre25-android-%s.tar.xz' % ABIS[abi][0])
    data = open(jre_txz, 'rb').read()
    if sha256(data) != ABIS[abi][1]:
        sys.exit('LOI: %s khong dung SHA-256' % jre_txz)
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(data))) as t:
        def norm(n):
            return posixpath.normpath(n[2:] if n.startswith('./') else n)
        members = {norm(m.name): m for m in t.getmembers()}
        for name, m in sorted(members.items()):
            target = m
            for _ in range(8):   # symlink (chủ yếu legal/*/ASSEMBLY_EXCEPTION...) -> chép nội dung tệp đích
                if not target.issym():
                    break
                target = members.get(posixpath.normpath(posixpath.join(posixpath.dirname(norm(target.name)), target.linkname)))
                if target is None:
                    sys.exit('LOI: JRE symlink hong %s' % name)
            if target.isfile():
                entries.append(('jre/' + name, t.extractfile(target).read()))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, b in sorted(entries):
            zi = zipfile.ZipInfo(name, FIXED)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, b)
    return buf.getvalue(), len(entries)


def keystore():
    d = os.path.join(DEPS, 'keys')
    ks = os.path.join(d, 'lodsc-release.jks')
    pw = os.path.join(d, 'keystore.pass')
    if not os.path.exists(ks):
        os.makedirs(d, exist_ok=True)
        password = secrets.token_urlsafe(24)
        open(pw, 'w', encoding='ascii').write(password)
        run(os.path.join(JDK17, 'bin', 'keytool.exe'), '-genkeypair', '-keystore', ks, '-alias', 'lodsc', '-keyalg', 'RSA',
            '-keysize', '4096', '-validity', '18250', '-storepass', password, '-keypass', password,
            '-dname', 'CN=LoD tieng Viet (Severed Chains), O=KhuongKid')
        print('tao khoa ky moi: %s (SAO LUU ca keystore.pass)' % ks)
    return ks, pw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--build', type=int, default=1)
    ap.add_argument('--zip')
    ap.add_argument('--abi', default='arm64-v8a', choices=sorted(ABIS))
    a = ap.parse_args()
    zip_path = a.zip or os.path.join(ROOT, 'release', 'LoD-SC-VN-v%s-sc-affcef0-windows.zip' % a.version)
    major, minor = (int(x) for x in a.version.split('.')[:2])
    version_code = major * 100000 + minor * 1000 + a.build
    version_name = '%s-android%d' % (a.version, a.build)

    work = os.path.join(ROOT, 'out', 'android', 'apk')
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    print('payload...')
    pay, count = payload(zip_path, a.version, a.abi)
    pay_ver = sha256(pay)[:32]
    print('payload.zip %.1f MB, %d tep' % (len(pay) / 1e6, count))

    print('aapt2...')
    manifest = open(os.path.join(AND, 'app', 'AndroidManifest.xml'), encoding='utf-8').read()
    manifest = manifest.replace('@VERSION_CODE@', str(version_code)).replace('@VERSION_NAME@', version_name)
    mpath = os.path.join(work, 'AndroidManifest.xml')
    open(mpath, 'w', encoding='utf-8').write(manifest)
    aapt2 = os.path.join(BT, 'aapt2.exe')
    run(aapt2, 'compile', '--dir', os.path.join(AND, 'app', 'res'), '-o', os.path.join(work, 'res.zip'))
    gen = os.path.join(work, 'gen')
    os.makedirs(gen)
    run(aapt2, 'link', '-o', os.path.join(work, 'base.apk'), '-I', ANDROID_JAR, '--manifest', mpath,
        os.path.join(work, 'res.zip'), '--java', gen, '--auto-add-overlay')

    print('javac + d8...')
    srcs = []
    for d in (os.path.join(AND, 'app', 'java'), SDL_JAVA, gen):
        for base, _, files in os.walk(d):
            srcs += [os.path.join(base, f) for f in files if f.endswith('.java')]
    cls = os.path.join(work, 'classes')
    os.makedirs(cls)
    argfile = os.path.join(work, 'srcs.txt')
    open(argfile, 'w', encoding='utf-8').write('\n'.join('"%s"' % s.replace('\\', '/') for s in srcs))
    run(os.path.join(JDK17, 'bin', 'javac.exe'), '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-nowarn', '-Xlint:-options',
        '-bootclasspath', ANDROID_JAR + os.pathsep + os.path.join(BT, 'core-lambda-stubs.jar'), '-d', cls, '@' + argfile)
    classes = []
    for base, _, files in os.walk(cls):
        classes += [os.path.join(base, f) for f in files if f.endswith('.class')]
    dex = os.path.join(work, 'dex')
    os.makedirs(dex)
    env = dict(os.environ, JAVA_HOME=JDK17)
    cargs = os.path.join(work, 'classes.txt')
    open(cargs, 'w', encoding='utf-8').write('\n'.join(c.replace('\\', '/') for c in classes))
    run(os.path.join(BT, 'd8.bat'), '--release', '--min-api', '29', '--lib', ANDROID_JAR, '--output', dex, '@' + cargs, env=env)

    print('ghep APK...')
    libs = {}
    for n in NATIVE_LIBS:
        libs[n] = open(os.path.join(DEPS, 'out', a.abi, n), 'rb').read()
    tag = ABIS[a.abi][0]
    for j in ('ffmpeg-8.0.1-1.5.13-android-%s.jar' % tag, 'javacpp-1.5.13-android-%s.jar' % tag):
        with zipfile.ZipFile(os.path.join(MAVEN, j)) as z:
            for n in z.namelist():
                if n.startswith('lib/%s/' % a.abi) and n.endswith('.so'):
                    libs[os.path.basename(n)] = z.read(n)
    unaligned = os.path.join(work, 'unaligned.apk')
    with zipfile.ZipFile(os.path.join(work, 'base.apk')) as base, zipfile.ZipFile(unaligned, 'w') as out:
        for info in base.infolist():
            zi = zipfile.ZipInfo(info.filename, FIXED)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == 'resources.arsc' or info.filename.endswith('.png') \
                else zipfile.ZIP_DEFLATED
            out.writestr(zi, base.read(info.filename))
        zi = zipfile.ZipInfo('classes.dex', FIXED)
        zi.compress_type = zipfile.ZIP_DEFLATED
        out.writestr(zi, open(os.path.join(dex, 'classes.dex'), 'rb').read())
        for n in sorted(libs):
            zi = zipfile.ZipInfo('lib/%s/' % a.abi + n, FIXED)
            zi.compress_type = zipfile.ZIP_STORED
            out.writestr(zi, libs[n])
        zi = zipfile.ZipInfo('assets/payload.zip', FIXED)
        zi.compress_type = zipfile.ZIP_STORED
        out.writestr(zi, pay)
        zi = zipfile.ZipInfo('assets/payload.version', FIXED)
        zi.compress_type = zipfile.ZIP_DEFLATED
        out.writestr(zi, pay_ver.encode())

    aligned = os.path.join(work, 'aligned.apk')
    run(os.path.join(BT, 'zipalign.exe'), '-f', '-P', '16', '4', unaligned, aligned)
    run(os.path.join(BT, 'zipalign.exe'), '-c', '-P', '16', '4', aligned)
    ks, pw = keystore()
    release = a.abi == 'arm64-v8a'   # bản x86_64 chỉ để thử trên giả lập: ra out/android, không ghi SHA256SUMS
    dest = os.path.join(ROOT, 'release') if release else os.path.join(ROOT, 'out', 'android')
    os.makedirs(dest, exist_ok=True)
    name = 'LoD-SC-VN-v%s-android-%s.apk' % (a.version, ABIS[a.abi][0])
    final = os.path.join(dest, name)
    sign_env = dict(env, LODSC_KS_PASS=open(pw, encoding='ascii').read().strip())
    run(os.path.join(BT, 'apksigner.bat'), 'sign', '--ks', ks, '--ks-key-alias', 'lodsc', '--ks-pass', 'env:LODSC_KS_PASS',
        '--key-pass', 'env:LODSC_KS_PASS', '--min-sdk-version', '29', '--out', final, aligned, env=sign_env)
    run(os.path.join(BT, 'apksigner.bat'), 'verify', '--min-sdk-version', '29', final, env=env)

    digest = sha256(open(final, 'rb').read())
    if release:
        sums = os.path.join(ROOT, 'release', 'SHA256SUMS.txt')
        old = [l for l in open(sums, encoding='ascii')] if os.path.exists(sums) else []
        with open(sums, 'w', encoding='ascii', newline='\n') as f:
            f.writelines(l for l in old if not l.rstrip().endswith('  ' + name))
            f.write('%s  %s\n' % (digest, name))
    print('APK: %s (%.1f MB) versionCode %d, SHA-256 %s' % (os.path.relpath(final, ROOT), os.path.getsize(final) / 1e6,
                                                         version_code, digest))


if __name__ == '__main__':
    main()
