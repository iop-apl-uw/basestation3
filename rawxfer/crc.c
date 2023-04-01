// -*- glider-c -*-
//
// Copyright (c) 2023  University of Washington.
// 
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
// 
// 1. Redistributions of source code must retain the above copyright notice, this
//    list of conditions and the following disclaimer.
// 
// 2. Redistributions in binary form must reproduce the above copyright notice,
//    this list of conditions and the following disclaimer in the documentation
//    and/or other materials provided with the distribution.
// 
// 3. Neither the name of the University of Washington nor the names of its
//    contributors may be used to endorse or promote products derived from this
//    software without specific prior written permission.
// 
// THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
// IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
// DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
// GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
// HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
// LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
// OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

/// @file crc.c
///
/// Generate the 16-bit Xmodem CRC for a block of data

/// xmodem polynomial:  x^16 + x^12 + x^5 + 1
///

static unsigned short
update(unsigned short crc, unsigned char data)
{
  int i;

   crc = crc ^ ((unsigned short) data << 8);
   for (i=0; i<8; i++) {
       if (crc & 0x8000)
           crc = (crc << 1) ^ 0x1021;
       else
           crc <<= 1;
    } 

    return crc;

}

unsigned short 
CalcCRC(unsigned char *block, unsigned long n)
{
    register int    i;
    unsigned long   j;
    unsigned short  c;
    unsigned        data;

    c = 0x0; 

    if(n <= 0)
    return 0;

    for (j = 0 ; j < n ; j++) {
        c = update(c, block[j]);
    }

    return c;
}

