import struct
import hashlib
import zlib
import sys
import os

def fix_dex_checksum(filepath):
    with open(filepath, 'rb') as f:
        data = bytearray(f.read())

    # 检查 magic
    if data[:4] != b'dex\n':
        print(f"Not a dex file: {filepath}")
        return False

    # 计算 signature = SHA-1(data[32:])
    signature = hashlib.sha1(data[32:]).digest()
    data[12:32] = signature

    # 计算 checksum = Adler-32(data[12:])
    checksum = zlib.adler32(data[12:]) & 0xFFFFFFFF
    data[8:12] = struct.pack('<I', checksum)

    with open(filepath, 'wb') as f:
        f.write(data)

    print(f"Fixed: {filepath}")
    return True

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '.'
    if os.path.isdir(path):
        for name in os.listdir(path):
            if name.endswith('.dex'):
                fix_dex_checksum(os.path.join(path, name))
    else:
        fix_dex_checksum(path)