//
// This code implements the MD5 message-digest algorithm.
// The algorithm is due to Ron Rivest.  This code was
// written by Colin Plumb in 1993, no copyright is claimed.
// This code is in the public domain; do with it what you wish.
//
// Equivalent code is available from RSA Data Security, Inc.
// This code has been tested against that, and is equivalent,
// except that you don't need to include two pages of legalese
// with every copy.
//

/// @file md5.c
///
/// To compute the message digest of a chunk of bytes, declare an
/// MD5Context structure, pass it to MD5Init, call MD5Update as
/// needed on buffers full of bytes, and then call MD5Final, which			
/// will fill a supplied 16-byte array with the digest.
///
/// Brutally hacked by John Walker back from ANSI C to K&R (no
/// prototypes) to maintain the tradition that Netfone will compile
/// with Sun's original "cc". 


#include	<stdio.h>
#include	<string.h>
#include	<stdlib.h>
#include	<stdarg.h>
#include	<errno.h>
#include	<ctype.h>
#include	<time.h>
#include	<sys/stat.h>
#include	<unistd.h>
#include "md5.h"

#define HIGHFIRST

#ifndef HIGHFIRST
#define byteReverse(buf, len)   /* Nothing */
#else
/*
 * Note: this code is harmless on little-endian machines.
 */
//void byteReverse(unsigned char *buf, unsigned longs)
void byteReverse(unsigned char *buf, uint32 longs)
{
    uint32 t;
    do {
        t = (uint32) ((unsigned) buf[3] << 8 | buf[2]) << 16 | ((unsigned) buf[1] << 8 | buf[0]);
        *(uint32 *) buf = t;
        buf += 4;
    } while (--longs);
}
#endif

/// Start MD5 accumulation.  Set bit count to 0 and buffer to mysterious
/// initialization constants.
void MD5Init(struct MD5Context *ctx)
{

    ctx->buf[0] = 0x67452301;
    ctx->buf[1] = 0xefcdab89;
    ctx->buf[2] = 0x98badcfe;
    ctx->buf[3] = 0x10325476;

    ctx->bits[0] = 0;
    ctx->bits[1] = 0;
}


/// Update context to reflect the concatenation of another buffer full
/// of bytes.
void MD5Update(struct MD5Context *ctx, unsigned char *buf, unsigned len)
{
    uint32 t;

    /* Update bitcount */

    t = ctx->bits[0];
    if ((ctx->bits[0] = t + ((uint32) len << 3)) < t)
        ctx->bits[1]++;     /* Carry from low to high */
    ctx->bits[1] += len >> 29;

    t = (t >> 3) & 0x3f;    /* Bytes already in shsInfo->data */

    /* Handle any leading odd-sized chunks */

    if (t) {
        unsigned char *p = (unsigned char *) ctx->in + t;

        t = 64 - t;
        if (len < t) {
            memcpy(p, buf, (size_t)len);
            return;
        }
        memcpy(p, buf, (size_t)t);
        byteReverse(ctx->in, 16);
        MD5Transform(ctx->buf, (uint32 *) ctx->in);
        buf += t;
        len -= t;
    }
    /* Process data in 64-byte chunks */

    while (len >= 64) {

        // GBS - 7/5/2016 The intrinsic generate by gcc under -O2 does not handle
        // unalinged input data - thus the hand coding
        //memcpy(ctx->in, buf, (size_t)64);
        for(int ii = 0; ii < 64; ii++) ctx->in[ii] = buf[ii];
        byteReverse(ctx->in, 16);
        MD5Transform(ctx->buf, (uint32 *) ctx->in);
        buf += 64;
        len -= 64;
    }

    /* Handle any remaining bytes of data. */

    memcpy(ctx->in, buf, (size_t)len);
}

/// Final wrapup - pad to 64-byte boundary with the bit pattern 
/// 1 0* (64-bit count of bits processed, MSB-first)
void MD5Final(unsigned char digest[16], struct MD5Context *ctx)
{
    unsigned count;
    unsigned char *p;

    /* Compute number of bytes mod 64 */
    count = (ctx->bits[0] >> 3) & 0x3F;

    /* Set the first char of padding to 0x80.  This is safe since there is
       always at least one byte free */
    p = ctx->in + count;
    *p++ = 0x80;

    /* Bytes of padding needed to make 64 bytes */
    count = 64 - 1 - count;

    /* Pad out to 56 mod 64 */
    if (count < 8) {
        /* Two lots of padding:  Pad the first block to 64 bytes */
        memset(p, 0, (size_t)count);
        byteReverse(ctx->in, 16);
        MD5Transform(ctx->buf, (uint32 *) ctx->in);

        /* Now fill the next block with 56 bytes */
        memset(ctx->in, 0, (size_t)56);
    } else {
        /* Pad block to 56 bytes */
        memset(p, 0, count - (size_t)8);
    }
    byteReverse(ctx->in, 14);

    /* Append length in bits and transform */
    ((uint32 *) ctx->in)[14] = ctx->bits[0];
    ((uint32 *) ctx->in)[15] = ctx->bits[1];

    MD5Transform(ctx->buf, (uint32 *) ctx->in);
    byteReverse((unsigned char *) ctx->buf, 4);
    memcpy(digest, ctx->buf, (size_t)16);
    memset(ctx, 0, sizeof(*ctx));        /* In case it's sensitive */
}


/* The four core functions - F1 is optimized somewhat */

//#define F1(x, y, z) (x & y | ~x & z)
#define F1(x, y, z) (z ^ (x & (y ^ z)))
#define F2(x, y, z) F1(z, x, y)
#define F3(x, y, z) (x ^ y ^ z)
#define F4(x, y, z) (y ^ (x | ~z))

///< This is the central step in the MD5 algorithm.
#define MD5STEP(f, w, x, y, z, data, s) \
    ( w += f(x, y, z) + data,  w = w<<s | w>>(32-s),  w += x )


/// The core of the MD5 algorithm, this alters an existing MD5 hash to
/// reflect the addition of 16 longwords of new data.  MD5Update blocks
/// the data and converts bytes into longwords for this routine.
void MD5Transform(uint32 buf[4], uint32 in[16])
{
    register uint32 a, b, c, d;

    a = buf[0];
    b = buf[1];
    c = buf[2];
    d = buf[3];

    MD5STEP(F1, a, b, c, d, in[0] + 0xd76aa478, 7);
    MD5STEP(F1, d, a, b, c, in[1] + 0xe8c7b756, 12);
    MD5STEP(F1, c, d, a, b, in[2] + 0x242070db, 17);
    MD5STEP(F1, b, c, d, a, in[3] + 0xc1bdceee, 22);
    MD5STEP(F1, a, b, c, d, in[4] + 0xf57c0faf, 7);
    MD5STEP(F1, d, a, b, c, in[5] + 0x4787c62a, 12);
    MD5STEP(F1, c, d, a, b, in[6] + 0xa8304613, 17);
    MD5STEP(F1, b, c, d, a, in[7] + 0xfd469501, 22);
    MD5STEP(F1, a, b, c, d, in[8] + 0x698098d8, 7);
    MD5STEP(F1, d, a, b, c, in[9] + 0x8b44f7af, 12);
    MD5STEP(F1, c, d, a, b, in[10] + 0xffff5bb1, 17);
    MD5STEP(F1, b, c, d, a, in[11] + 0x895cd7be, 22);
    MD5STEP(F1, a, b, c, d, in[12] + 0x6b901122, 7);
    MD5STEP(F1, d, a, b, c, in[13] + 0xfd987193, 12);
    MD5STEP(F1, c, d, a, b, in[14] + 0xa679438e, 17);
    MD5STEP(F1, b, c, d, a, in[15] + 0x49b40821, 22);

    MD5STEP(F2, a, b, c, d, in[1] + 0xf61e2562, 5);
    MD5STEP(F2, d, a, b, c, in[6] + 0xc040b340, 9);
    MD5STEP(F2, c, d, a, b, in[11] + 0x265e5a51, 14);
    MD5STEP(F2, b, c, d, a, in[0] + 0xe9b6c7aa, 20);
    MD5STEP(F2, a, b, c, d, in[5] + 0xd62f105d, 5);
    MD5STEP(F2, d, a, b, c, in[10] + 0x02441453, 9);
    MD5STEP(F2, c, d, a, b, in[15] + 0xd8a1e681, 14);
    MD5STEP(F2, b, c, d, a, in[4] + 0xe7d3fbc8, 20);
    MD5STEP(F2, a, b, c, d, in[9] + 0x21e1cde6, 5);
    MD5STEP(F2, d, a, b, c, in[14] + 0xc33707d6, 9);
    MD5STEP(F2, c, d, a, b, in[3] + 0xf4d50d87, 14);
    MD5STEP(F2, b, c, d, a, in[8] + 0x455a14ed, 20);
    MD5STEP(F2, a, b, c, d, in[13] + 0xa9e3e905, 5);
    MD5STEP(F2, d, a, b, c, in[2] + 0xfcefa3f8, 9);
    MD5STEP(F2, c, d, a, b, in[7] + 0x676f02d9, 14);
    MD5STEP(F2, b, c, d, a, in[12] + 0x8d2a4c8a, 20);

    MD5STEP(F3, a, b, c, d, in[5] + 0xfffa3942, 4);
    MD5STEP(F3, d, a, b, c, in[8] + 0x8771f681, 11);
    MD5STEP(F3, c, d, a, b, in[11] + 0x6d9d6122, 16);
    MD5STEP(F3, b, c, d, a, in[14] + 0xfde5380c, 23);
    MD5STEP(F3, a, b, c, d, in[1] + 0xa4beea44, 4);
    MD5STEP(F3, d, a, b, c, in[4] + 0x4bdecfa9, 11);
    MD5STEP(F3, c, d, a, b, in[7] + 0xf6bb4b60, 16);
    MD5STEP(F3, b, c, d, a, in[10] + 0xbebfbc70, 23);
    MD5STEP(F3, a, b, c, d, in[13] + 0x289b7ec6, 4);
    MD5STEP(F3, d, a, b, c, in[0] + 0xeaa127fa, 11);
    MD5STEP(F3, c, d, a, b, in[3] + 0xd4ef3085, 16);
    MD5STEP(F3, b, c, d, a, in[6] + 0x04881d05, 23);
    MD5STEP(F3, a, b, c, d, in[9] + 0xd9d4d039, 4);
    MD5STEP(F3, d, a, b, c, in[12] + 0xe6db99e5, 11);
    MD5STEP(F3, c, d, a, b, in[15] + 0x1fa27cf8, 16);
    MD5STEP(F3, b, c, d, a, in[2] + 0xc4ac5665, 23);

    MD5STEP(F4, a, b, c, d, in[0] + 0xf4292244, 6);
    MD5STEP(F4, d, a, b, c, in[7] + 0x432aff97, 10);
    MD5STEP(F4, c, d, a, b, in[14] + 0xab9423a7, 15);
    MD5STEP(F4, b, c, d, a, in[5] + 0xfc93a039, 21);
    MD5STEP(F4, a, b, c, d, in[12] + 0x655b59c3, 6);
    MD5STEP(F4, d, a, b, c, in[3] + 0x8f0ccc92, 10);
    MD5STEP(F4, c, d, a, b, in[10] + 0xffeff47d, 15);
    MD5STEP(F4, b, c, d, a, in[1] + 0x85845dd1, 21);
    MD5STEP(F4, a, b, c, d, in[8] + 0x6fa87e4f, 6);
    MD5STEP(F4, d, a, b, c, in[15] + 0xfe2ce6e0, 10);
    MD5STEP(F4, c, d, a, b, in[6] + 0xa3014314, 15);
    MD5STEP(F4, b, c, d, a, in[13] + 0x4e0811a1, 21);
    MD5STEP(F4, a, b, c, d, in[4] + 0xf7537e82, 6);
    MD5STEP(F4, d, a, b, c, in[11] + 0xbd3af235, 10);
    MD5STEP(F4, c, d, a, b, in[2] + 0x2ad7d2bb, 15);
    MD5STEP(F4, b, c, d, a, in[9] + 0xeb86d391, 21);

    buf[0] += a;
    buf[1] += b;
    buf[2] += c;
    buf[3] += d;
}

/// Compares two MD5 hashes
/// \return 0 if they are equal, non-zero if they are not
int
md5_compare(char *sig1,
            char *sig2)
{
    char csig1[16];
    char csig2[16];
    char *clabel1;
    char *clabel2;
    int j;
    char *hexfmt = "%02x"; // assume (coerce) signature to lower case
    unsigned int bp;

    if(!sig1 || !sig2) {
        return -1;
    }

    if (strlen(sig1) != 32 || strlen(sig2) != 32) {
        return -1;
    }
    
    for (j = 0; j < 31; j++) {
        sig1[j] = tolower((unsigned char)sig1[j]);
        sig2[j] = tolower((unsigned char)sig2[j]);
    }
    
    memset(csig1, 0, (size_t)16);
    memset(csig1, 0, (size_t)16);
    
    clabel1 = sig1;
    clabel2 = sig2;
    
    for (j = 0; j < 16; j++) {
        if (isxdigit((int) clabel1[0]) && isxdigit((int) clabel1[1]) &&
            sscanf((sig1 + (j * 2)), hexfmt, &bp) == 1) {
            csig1[j] = (unsigned char) bp;
        } else {
            return -1;
        }
        clabel1 += 2;

        if (isxdigit((int) clabel2[0]) && isxdigit((int) clabel2[1]) &&
            sscanf((sig2 + (j * 2)), hexfmt, &bp) == 1) {
            csig2[j] = (unsigned char) bp;
        } else {
            return -1;
        }
        clabel2 += 2;
    }
    
    for (j = 0; j < sizeof(csig1); j++) {
        if (csig1[j] != csig2[j]) {
            return -1;
        }
    }
    return 0;
}


/// Computes the signature from the file
/// \return 
int
md5_compute(char *filename,
            char *output_sig)
{
    FILE *in = NULL;
    struct MD5Context md5c;
    char signature[16];
    char *hexfmt = "%02x"; // assume (coerce) signature to lower case
    int j;
    long bytes = 0;
    char buff[4];
    int retval = 1;
    char *in_buff = NULL;

    if(!filename || !output_sig) {
        goto exit;
    }

    in_buff = malloc(MD5_COPY_BUFF);
    if(!in_buff) {
        retval = 1;
        goto exit;
    }

    // Compute the signature of the file
    if ((in = fopen(filename, "r"))) {
        MD5Init(&md5c);
        while ((bytes = (int) fread(in_buff, 1L, MD5_COPY_BUFF, in))) {
            if (bytes == EOF) {
                break; // done?
            }
            MD5Update(&md5c, (unsigned char *) in_buff, (unsigned) bytes);
        }
        MD5Final((unsigned char *) signature, &md5c);
        fclose(in);
    } else {
        goto exit;
    }
   
    // this takes a while when capturing so use line to buffer it
    output_sig[0] = '\0'; // clear line
    for (j = 0; j < sizeof(signature); j++) {
        sprintf(buff, hexfmt, (signature[j] & 0xFF));
        strcat(output_sig,buff);
    }
    retval = 0;

 exit:
    if(in_buff) {
        free(in_buff);
    }
    return retval;
}

#ifdef STANDALONE
int
main(int argc, char *argv[])
{
    char signature[65];

    md5_compute(argv[1], signature);
    printf("%s\n", signature);
}
#endif
