"""POSIX cksum(1)'s CRC, for a key a shell tool once computed with cksum and
a Python one must still match. Imported, never run directly; stdlib only.

    key = cksum.cksum(url.encode())   # the number `printf %s "$url" | cksum` prints first

The algorithm is the one POSIX specifies: CRC-32 over polynomial 0x04C11DB7,
most significant bit first, over the data and then its length in the fewest
little-endian bytes, complemented. Not zlib.crc32, which reflects its bits
and gives a different number.
"""


def cksum(data):
    """The CRC cksum(1) prints for data (bytes), as an int."""
    crc = 0

    def feed(byte):
        nonlocal crc
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7 if crc & 0x80000000 else crc << 1) & 0xFFFFFFFF

    for b in data:
        feed(b)
    n = len(data)
    while n:
        feed(n & 0xFF)
        n >>= 8
    return ~crc & 0xFFFFFFFF
