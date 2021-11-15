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

/// @file md5.h

#ifndef MD5_H
#define MD5_H

#define MD5_COPY_BUFF 4096    ///< Buffer size for MD5 to use when copying
#define MD5_SIG_BUFF 34       ///< Buffer size for MD5 signatures

#ifdef __alpha
typedef unsigned int uint32;
#else
typedef unsigned int uint32;
#endif

struct MD5Context {
        uint32 buf[4];
        uint32 bits[2];
        unsigned char in[64];
};

extern void MD5Init(struct MD5Context *);
extern void MD5Update(struct MD5Context *, unsigned char *, unsigned);
extern void MD5Final(unsigned char digest[16], struct MD5Context *);
extern void MD5Transform(uint32 buf[4], uint32 in[16]);
void byteReverse(unsigned char *, uint32);

int md5_compare(char *,char *);
int md5_compute(char *, char *);
int md5_compute_buffer(char *in_buff, int num_bytes, char *output_sig);


/*
 * This is needed to make RSAREF happy on some MS-DOS compilers.
 */
typedef struct MD5Context MD5_CTX;

#endif /* !MD5_H */
