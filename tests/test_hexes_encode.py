from stoop.hexes import decode_ring, encode_ring


def test_ring_round_trip():
    ring = [(-73.98765, 40.72345), (-73.98601, 40.72399), (-73.98700, 40.72250), (-73.98765, 40.72345)]
    flat = encode_ring(ring)
    assert flat[:2] == [-7398765, 4072345] and flat[2:4] == [164, 54]
    assert decode_ring(flat) == ring
