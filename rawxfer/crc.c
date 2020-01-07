// -*- glider-c -*-
//
// Copyright (c) 1997-2002, 2005 University of Washington.  All rights reserved.
//
// This file contains proprietary information and remains the 
// unpublished property of the University of Washington. Use, disclosure,
// or reproduction is prohibited except as permitted by express written
// license agreement with the University of Washington.
//

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

