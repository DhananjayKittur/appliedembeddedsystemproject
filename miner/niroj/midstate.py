
import struct
import util

# Some SHA-256 constants...
K = [
     0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
     0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
     0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
     0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
     0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
     0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
     0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
     0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
     0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
     0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
     0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ]

A0 = 0x6a09e667
B0 = 0xbb67ae85
C0 = 0x3c6ef372
D0 = 0xa54ff53a
E0 = 0x510e527f
F0 = 0x9b05688c
G0 = 0x1f83d9ab
H0 = 0x5be0cd19

def rotateright(i,p):
    """i>>>p"""
    p &= 0x1F # p mod 32
    return i>>p | ((i<<(32-p)) & 0xFFFFFFFF)

def addu32(*i):
    return sum(list(i))&0xFFFFFFFF

def calculateMidstate(data, state=None, rounds=None, debug=False):
    """Given a 512-bit (64-byte) block of (big-endian byteswapped) data,
    calculate a Bitcoin-style midstate. (That is, if SHA-256 were big-endian
    and only hashed the first block of input.)
    """
    if len(data) != 64:
        raise ValueError('data must be 64 bytes long')
    w = list(struct.unpack('>IIIIIIIIIIIIIIII', data))
    if debug:
        print w


    if state is not None:
        if len(state) != 32:
            raise ValueError('state must be 32 bytes long')
        a,b,c,d,e,f,g,h = struct.unpack('>IIIIIIII', state)
        if debug:
            print "Second iteration:","a=", a, "b=", b, "c=", c, "d=", d, "e=", e, "f=", f, "g=", g, "h=", h
        a_0, b_0, c_0, d_0, e_0, f_0, g_0, h_0 = a,b,c,d,e,f,g,h 
    else:
        a = A0
        b = B0
        c = C0
        d = D0
        e = E0
        f = F0
        g = G0
        h = H0

    consts = K if rounds is None else K[:rounds]
    for k in consts:
        s0 = rotateright(a,2) ^ rotateright(a,13) ^ rotateright(a,22)
        s1 = rotateright(e,6) ^ rotateright(e,11) ^ rotateright(e,25)
        ma = (a&b) ^ (a&c) ^ (b&c)
        ch = (e&f) ^ ((~e)&g)

        h = addu32(h,w[0],k,ch,s1)
        d = addu32(d,h)
        h = addu32(h,ma,s0)

        a,b,c,d,e,f,g,h = h,a,b,c,d,e,f,g

        s0 = rotateright(w[1],7) ^ rotateright(w[1],18) ^ (w[1] >> 3)
        s1 = rotateright(w[14],17) ^ rotateright(w[14],19) ^ (w[14] >> 10)
        w.append(addu32(w[0], s0, w[9], s1))
        w.pop(0)
    if debug:
        print "Before", "a=", a, "b=", b, "c=", c, "d=", d, "e=", e, "f=", f, "g=", g, "h=", h
    if rounds is None:
        a = addu32(a, A0)
        b = addu32(b, B0)
        c = addu32(c, C0)
        d = addu32(d, D0)
        e = addu32(e, E0)
        f = addu32(f, F0)
        g = addu32(g, G0)
        h = addu32(h, H0)
    else:
        a = addu32(a, a_0)
        b = addu32(b, b_0)
        c = addu32(c, c_0)
        d = addu32(d, d_0)
        e = addu32(e, e_0)
        f = addu32(f, f_0)
        g = addu32(g, g_0)
        h = addu32(h, h_0)

    ga = a
    gb = b
    gc = c
    gd = d
    ge = e
    gf = f
    gg = g
    gh = h
    if debug:
        print "a=", a, "b=", b, "c=", c, "d=", d, "e=", e, "f=", f, "g=", g, "h=", h
    return struct.pack('>IIIIIIII', a, b, c, d, e, f, g, h)
