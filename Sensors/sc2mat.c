//
// Copyright (c) 2018 University of Washington.  All rights reserved.
//
// This file contains proprietary information and remains the 
// unpublished property of the University of Washington. Use, disclosure,
// or reproduction is prohibited.
//

// gcc -o sc2mat sc2mat.c

# include <stdio.h>
# include <math.h>
# include <string.h>
# include <time.h>
# include <stdlib.h>

typedef struct {
   int  type;
   int  mrows;
   int ncols;
   int imagf;
   int namlen;
} MATheader;

static FILE	*fp, *out;

static int      num_beams;
static int      num_cells;
static int      count;
static int      countAtt;
static int      countBurst;

unsigned short burstBeams;    
unsigned short burstCells;
unsigned short burst_cellSize;

static double **beamv[4];
static double	*temperature;
static double	*pressure;
static double   *battery;
static double	*heading;
static double	*roll;
static double	*pitch; 
static double	*t;

static double   *tAtt;
static double   *pressureAtt;
static double   *headingAtt;
static double   *pitchAtt;
static double   *rollAtt;
static double   *magXAtt;
static double   *magYAtt;
static double   *magZAtt;

static double g_cellSize[1] = {0};
static double g_blanking[1] = {0};
static double g_soundspeed[1] = {0};
static double g_burstSize[1] = {0};

static double *tBurst;
static double *pressureBurst;
static double *pitchBurst;
static double *rollBurst;
static double *headingBurst;
static double  **corr = NULL;


static int 
architecture ( )
{
   int  x = 1;

   if (*((char *) &x) == 1)
      return 0;
   else
      return 1;
}

static void 
MatlabDoubleVector (double *a, int n, char *name, FILE *fp)
{
   int         arch;
   int         mopt;
   double       x;
   unsigned    i;
   MATheader   h;

   arch = architecture ( );


   mopt = arch*1000 + 0*100 + 0*10 + 0*1;
                      /* reserved */
                              /* double precision */
                                     /* numeric full matrix */
   h.type = mopt;
   h.mrows = n;
   h.ncols = 1;
   h.imagf = 0;
   h.namlen = strlen(name) + 1;

   fwrite (&h, sizeof(MATheader), 1, fp);
   fwrite (name, sizeof(char), h.namlen, fp);

   for (i = 0 ; i < n ; i++) {
      x = a [i];
      fwrite (&x, sizeof(double), 1, fp);
   }

   return;
}

static void 
MatlabVector (short *a, int n, char *name, FILE *fp, int unsign)
{
   int         arch;
   int         mopt;
   short       x;
   unsigned    i;
   MATheader   h;

   arch = architecture ( );


   mopt = arch*1000 + 0*100 + (3 + unsign)*10 + 0*1;
                      /* reserved */
                              /* short precision */
                                     /* numeric full matrix */
   h.type = mopt;
   h.mrows = n;
   h.ncols = 1;
   h.imagf = 0;
   h.namlen = strlen(name) + 1;

   fwrite (&h, sizeof(MATheader), 1, fp);
   fwrite (name, sizeof(char), h.namlen, fp);

   for (i = 0 ; i < n ; i++) {
      x = (short) a [i];
      fwrite (&x, sizeof(short), 1, fp);
   }

   return;
}

static void 
MatlabMatrix (short **a, int nr, int nc, char *name, FILE *fp)
{
   int         arch;
   int         mopt;
   short       x;
   unsigned    i, j;
   MATheader   h;

   arch = architecture ( );

   mopt = arch*1000 + 0*100 + 3*10 + 0*1;
                      /* reserved */
                              /* short precision */
                                     /* numeric full matrix */
   h.type = mopt;
   h.mrows = nr;
   h.ncols = nc;
   h.imagf = 0;

   h.namlen = strlen(name) + 1;

   fwrite (&h, sizeof(MATheader), 1, fp);
   fwrite (name, sizeof(char), h.namlen, fp);

   for (i = 0 ; i < nc ; i++) {
      for (j = 0 ; j < nr ; j++) {
         x = a [j][i];
         fwrite (&x, sizeof(short), 1, fp);
      }
   }

   return;
}

static void 
MatlabDoubleMatrix (double **a, int nr, int nc, char *name, FILE *fp)
{
   int         arch;
   int         mopt;
   double       x;
   unsigned    i, j;
   MATheader   h;

   arch = architecture ( );

   mopt = arch*1000 + 0*100 + 0*10 + 0*1;
                      /* reserved */
                              /* double float precision */
                                     /* numeric full matrix */
   h.type = mopt;
   h.mrows = nr;
   h.ncols = nc;
   h.imagf = 0;

   h.namlen = strlen(name) + 1;

   fwrite (&h, sizeof(MATheader), 1, fp);
   fwrite (name, sizeof(char), h.namlen, fp);

   for (i = 0 ; i < nc ; i++) {
      for (j = 0 ; j < nr ; j++) {
         x = a [j][i];
         fwrite (&x, sizeof(double), 1, fp);
      }
   }

   return;
}

static double *
Dvector(int nr)
{
   double     *x;

   x = (double *) malloc(sizeof(double) * nr);

   return x;
}

static double **
Darray(int nr, int nc)
{
   short      i;
   double    **x;

   x = (double **) malloc(sizeof(double *) * nr);
   for (i = 0 ; i < nr ; i++)
      x [i] = (double *) malloc(sizeof(double) * nc);

   return x;
}

static short *
vector(int nr)
{
   int      i;
   short     *x;

   x = (short *) malloc(sizeof(short) * nr);

   return x;
}

static short **
array(int nr, int nc)
{
   short      i;
   short    **x;

   x = (short **) malloc(sizeof(short *) * nr);
   for (i = 0 ; i < nr ; i++)
      x [i] = (short *) malloc(sizeof(short) * nc);

   return x;
}


static void 
WriteMatlab(char *fname)
{
//   fprintf (stderr,"%02d:%02d:%02d.%02d on %02d/%02d/%04d\n",
//            tm.tm_hour, tm.tm_min, tm.tm_sec, hsec, 
//            tm.tm_mon + 1, tm.tm_mday, tm.tm_year + 1900);
   fprintf(stderr, "%s: %d ensembles\n", fname, count);
   fprintf(stderr, "%s: %d burst pings\n", fname, countBurst);
   fprintf(stderr, "%s: %d attitude records\n", fname, countAtt);

   MatlabDoubleVector(g_blanking, 1, "blanking", out);
   MatlabDoubleVector(g_cellSize, 1, "cellSize", out);
   MatlabDoubleVector(g_soundspeed, 1, "soundspeed", out);

   MatlabDoubleMatrix(beamv[0], num_cells, count, "velX", out);   
   MatlabDoubleMatrix(beamv[1], num_cells, count, "velY", out);   
   MatlabDoubleMatrix(beamv[2], num_cells, count, "velZ", out);   

   MatlabDoubleVector(pressure, count, "pressure", out);
   MatlabDoubleVector(battery, count, "battery", out);
   MatlabDoubleVector(temperature, count, "temperature", out);
   MatlabDoubleVector(heading, count, "heading", out);
   MatlabDoubleVector(pitch, count, "pitch", out);
   MatlabDoubleVector(roll, count, "roll", out);

   MatlabDoubleVector(t, count, "time", out);

   if (countAtt > 0) {
      MatlabDoubleVector(pressureAtt, countAtt, "pressureAtt", out);
      MatlabDoubleVector(headingAtt, countAtt, "headingAtt", out);
      MatlabDoubleVector(pitchAtt, countAtt, "pitchAtt", out);
      MatlabDoubleVector(rollAtt, countAtt, "rollAtt", out);
      MatlabDoubleVector(tAtt, countAtt, "timeAtt", out);
      MatlabDoubleVector(magXAtt, countAtt, "magXAtt", out);
      MatlabDoubleVector(magYAtt, countAtt, "magYAtt", out);
      MatlabDoubleVector(magZAtt, countAtt, "magZAtt", out);
   }

   if (countBurst > 0) {
      MatlabDoubleVector(pressureBurst, countBurst, "pressureBurst", out);
      MatlabDoubleVector(headingBurst, countBurst, "headingBurst", out);
      MatlabDoubleVector(pitchBurst, countBurst, "pitchBurst", out);
      MatlabDoubleVector(rollBurst, countBurst, "rollBurst", out);
      MatlabDoubleVector(tBurst, countBurst, "timeBurst", out);
      MatlabDoubleMatrix(corr, burstCells, countBurst, "corrBurst", out);
   }
   fclose(out);

   exit (0);
}

int 
main(int argc, char *argv[])
{
    char c;
    double scale;
    unsigned char b, n, ii, j, k, id, fam;
    unsigned short i;
    unsigned short sz, ckd, ckh;
    struct tm tm;
    time_t tt, ttAtt;
    int    max_count, max_countAtt;
    unsigned short sync;
    unsigned char  sync1;
    long tell;
    unsigned char  buff[65536];
    unsigned short cellSize;
    unsigned short blanking;
    unsigned short soundSpeed;
    char           velocityScaling;
    int            epoch;
    unsigned int   pressureInstant;
    unsigned int   pressureAvg;
    short          temperatureAvg;
    unsigned short headingAvg;
    unsigned short headingInstant;
    short          pitchAvg;
    short          pitchInstant;
    short          rollAvg;
    short          rollInstant;
    unsigned short batteryAvg;
    short          hVel[65536];
    unsigned char  hCorr[65536];
    short          magnHxHyHz[3];

    count = 0;
    countAtt = 0;
    countBurst = 0;
    max_count = max_countAtt = 200000;

    setenv("TZ", "", 1); // null string is UTC
    tzset();

    if (argc < 3 
        || (out = fopen(argv[argc-1], "wb")) == NULL) {
       
        printf("sc2mat in1 in2 in3 ... out\n");
        return 1;
    } 

    for (ii = 1 ; ii <= argc - 2 ; ii++) {
        if ((fp = fopen(argv[ii], "rb")) == NULL)
            break;

        while(!feof(fp)) {
            if (fread(&sync1, sizeof(unsigned char), 1, fp) != 1)
                break;

            if (sync1 == '%') {
                if (fread(&sync1, sizeof(unsigned char), 1, fp) != 1)
                    break;
               
                if (sync1 == ' ') {
                    printf("%% ");    
                    while(fread(&c, sizeof(char), 1, fp) == 1 && c != 10) {
                        printf("%c", c);
                    }
                    printf("\n");
                }
                continue;
            }
            else  if (sync1 != 0xa5) {
                printf("sync 1 after header block = %x\n", sync1);
                continue;
            }
            if (fread(&sync1, sizeof(unsigned char), 1, fp) != 1)
                break;

            if (sync1 != 0x0a) {
                printf("sync1 after ad2cp header start = %x\n", sync1);
                continue;
            }
 
            if (fread(buff, sizeof(unsigned char), 8, fp) != 8)
                break;

            id  = buff[0];
            fam = buff[1];
            sz = *((unsigned short *) &(buff[2]));
            ckd = buff[4] + buff[5]*256;
            ckh = buff[6] + buff[7]*256;

            printf("header size = %d\n", sz);
            for (i = 0 ; i < sz ; i++) {
                if (fread(&buff[i], sizeof(unsigned char), 1, fp) != 1)
                    break;

                if (buff[i] == 0xa1) {
                    fseek(fp, -1, SEEK_CUR);
                    break;
                }
            }

	        tell = ftell(fp);
            printf("after header tell = %ld, count = %d\n", tell, count);

            if (id == 0xa0) {
                buff[sz] = 0;
                break;
            }
        }
        while(!feof(fp)) {
            if (fread(&sync, sizeof(unsigned short), 1, fp) != 1)
                break;

            if (sync == 0xa5a1) {

                fread(&num_beams, sizeof(unsigned short), 1, fp);
                fread(&num_cells, sizeof(unsigned short), 1, fp);
                fread(&cellSize, sizeof(unsigned short), 1, fp);
                fread(&blanking, sizeof(unsigned short), 1, fp); // 8
                fread(&soundSpeed, sizeof(unsigned short), 1, fp);
                fread(&velocityScaling, sizeof(char), 1, fp);
	            tell = ftell(fp);
                printf("after meta tell = %ld, count = %d\n", tell, count);
                g_cellSize[0] = cellSize;
                g_blanking[0] = blanking;
                g_soundspeed[0] = soundSpeed;
                continue;
            }
            if (sync == 0xa5a2) {

                fread(&burstBeams, sizeof(unsigned short), 1, fp);
                fread(&burstCells, sizeof(unsigned short), 1, fp);
                fread(&burst_cellSize, sizeof(unsigned short), 1, fp);
	            tell = ftell(fp);
                printf("after burst meta tell = %ld, count = %d\n", tell, count);
                g_burstSize[0] = burst_cellSize;
                printf("0xa5a2 record: %d %d\n", burstBeams, burstCells);
                continue;
            }


            if (sync == 0xa5a3) {
                fread(&epoch, sizeof(int), 1, fp);
                fread(&pressureAvg, sizeof(unsigned int), 1, fp);
                fread(&headingAvg, sizeof(unsigned short), 1, fp);
                fread(&pitchAvg, sizeof(short), 1, fp);
                fread(&rollAvg, sizeof(short), 1, fp);
                fread(&magnHxHyHz, sizeof(unsigned short), 3, fp);

                if (countAtt == 0) {
                    tAtt           = Dvector(max_countAtt);
                    pressureAtt    = Dvector(max_countAtt); 
                    pitchAtt       = Dvector(max_countAtt); 
                    rollAtt        = Dvector(max_countAtt); 
                    headingAtt     = Dvector(max_countAtt); 
                    magXAtt     = Dvector(max_countAtt); 
                    magYAtt     = Dvector(max_countAtt); 
                    magZAtt     = Dvector(max_countAtt); 
                }

                tAtt[countAtt]        = epoch;
                pressureAtt[countAtt] = pressureAvg*0.001;
                headingAtt[countAtt]  = headingAvg*0.01;
                rollAtt[countAtt]     = rollAvg*0.01;
                pitchAtt[countAtt]    = pitchAvg*0.01;
                magXAtt[countAtt]    = magnHxHyHz[0];
                magYAtt[countAtt]    = magnHxHyHz[1];
                magZAtt[countAtt]    = magnHxHyHz[2];
                countAtt ++;
	            tell = ftell(fp);
                // printf("after att tell = %ld, count = %d\n", tell, countAtt);

                continue;
            }

            if (sync == 0x2025) {
                printf("%% ");    
                while(fread(&c, sizeof(char), 1, fp) == 1 && c != 10) {
                    printf("%c", c);
                }
                printf("\n");
                continue;
            }

            if (sync == 0xa5a6) {
                fread(&epoch, sizeof(int), 1, fp);
                fread(&pressureInstant, sizeof(unsigned int), 1, fp);
                fread(&headingInstant, sizeof(unsigned short), 1, fp);
                fread(&pitchInstant, sizeof(short), 1, fp);
                fread(&rollInstant, sizeof(short), 1, fp);

                printf("0xa5a6 record: %d %u\n", epoch, pressureInstant);

                if (countBurst == 0) {
                    corr = Darray(burstCells, max_count);
                    tBurst = Dvector(max_count);
                    pressureBurst = Dvector(max_count);
                    headingBurst  = Dvector(max_count);
                    pitchBurst    = Dvector(max_count);
                    rollBurst     = Dvector(max_count);
                }

                tBurst[countBurst]        = epoch;
                pressureBurst[countBurst] = pressureInstant*0.001;
                headingBurst[countBurst]  = headingInstant*0.01;
                pitchBurst[countBurst]    = pitchInstant*0.01;
                rollBurst[countBurst]     = rollInstant*0.01;
                fread(hCorr, sizeof(unsigned char), burstCells * burstBeams, fp);
                for (i = 0 ; i < burstCells ; i++)
                    corr[i][countBurst] = hCorr[i];

                countBurst ++;
                continue;
            }

            if (sync == 0xa5a5) {
                fread(&epoch, sizeof(int), 1, fp);
                fread(&pressureInstant, sizeof(unsigned int), 1, fp);

                scale = pow(10.0, velocityScaling);
                printf("0xa5a5 record: %d %d %d %u %f\n", num_beams, num_cells, epoch, pressureInstant, scale); 

                fread(&pressureAvg, sizeof(unsigned int), 1, fp);
                fread(&temperatureAvg, sizeof(short), 1, fp);
                fread(&headingAvg, sizeof(unsigned short), 1, fp);
                fread(&pitchAvg, sizeof(short), 1, fp);
                fread(&rollAvg, sizeof(short), 1, fp);
                fread(&batteryAvg, sizeof(unsigned short), 1, fp);

                 if (count == 0) {
                    for (j = 0 ; j < 4 ; j++) {
                        beamv[j] = Darray(num_cells, max_count);
                    }
                    t           = Dvector(max_count);
                    pressure    = Dvector(max_count); 
                    pitch       = Dvector(max_count); 
                    roll        = Dvector(max_count); 
                    heading     = Dvector(max_count); 
                    temperature = Dvector(max_count); 
                    battery     = Dvector(max_count); 
                }

                pressure[count]    = pressureAvg*0.001;
                temperature[count] = temperatureAvg*0.01;
                heading[count]     = headingAvg*0.01;
                pitch[count]       = pitchAvg*0.01;
                roll[count]        = rollAvg*0.01;
                battery[count]     = batteryAvg*0.001;

                t[count] = epoch;
            
                fread(hVel, sizeof(short), num_beams*num_cells, fp);

            
                for (i = 0 ; i < num_cells ; i ++) {
                    for (j = 0 ; j < num_beams ; j ++) {
                        beamv[j][i][count] = scale*hVel[j*num_cells + i];
                    } 
                }
                count ++;
                tell = ftell(fp);
                // printf("tell = %ld, count = %d\n", tell, count);
                continue;
            }

            printf("skipping 1 %x\n", sync);
        }
        fclose(fp);
    }  
    WriteMatlab (argv[argc-1]);

    return 0;      
}
