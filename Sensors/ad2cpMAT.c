//
// Copyright (c) 2018, 2021 University of Washington.  All rights reserved.
//
// This file contains proprietary information and remains the 
// unpublished property of the University of Washington. Use, disclosure,
// or reproduction is prohibited.
//

// gcc -o ad2cpMAT ad2cpMAT.c

# include <stdio.h>
# include <math.h>
# include <string.h>
# include <time.h>
# include <stdlib.h>
# include <unistd.h>

int verbose = 0;

typedef struct {
    int  type;
    int  mrows;
    int ncols;
    int imagf;
    int namlen;
} MATheader;

static int       nav_present, bt_present;

static long position;

static FILE	*fp, *out;

static int      num_beams;
static int      num_cells;
static int      count;

static double      cellSize;
static double      blanking;

static double **beamv[4];
static short  **corr[4];
static short  **amp[4];
static double  **echo = NULL;
static double	*temperature;
static double	*pressure;
static double	*heading;
static double	*roll;
static double	*pitch; 
static double	*t;
static short	*magX;
static short	*magY;
static short	*magZ;
static short    *beamN = NULL;
static short    *power = NULL;

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
WriteMatlab(char *fname, int ampIncluded, int corrIncluded )
{
//   fprintf (stderr,"%02d:%02d:%02d.%02d on %02d/%02d/%04d\n",
//            tm.tm_hour, tm.tm_min, tm.tm_sec, hsec, 
//            tm.tm_mon + 1, tm.tm_mday, tm.tm_year + 1900);
    if(verbose) {
        fprintf(stdout, "%s: %d ensembles\n", fname, count);
        fprintf(stdout, "ampIncluded:%d corrIncluded:%d num_beams:%d\n",
                ampIncluded, corrIncluded, num_beams);
    }
    

    if (echo) {
        MatlabDoubleMatrix(echo, num_cells, count, "echo", out);   
        MatlabVector(beamN, count, "beam", out, 0);
        MatlabVector(power, count, "power", out, 0);
    }
    else {
        if (num_beams == 4) {
            MatlabDoubleMatrix(beamv[0], num_cells, count, "vel1", out);   
            MatlabDoubleMatrix(beamv[1], num_cells, count, "vel2", out);   
            MatlabDoubleMatrix(beamv[2], num_cells, count, "vel3", out);
            MatlabDoubleMatrix(beamv[3], num_cells, count, "vel4", out);
        } else {
            MatlabDoubleMatrix(beamv[0], num_cells, count, "velX", out);   
            MatlabDoubleMatrix(beamv[1], num_cells, count, "velY", out);   
            MatlabDoubleMatrix(beamv[2], num_cells, count, "velZ", out);
        }

        if( corrIncluded ) {
            MatlabMatrix(corr[0], num_cells, count, "corr1", out);   
            MatlabMatrix(corr[1], num_cells, count, "corr2", out);   
            MatlabMatrix(corr[2], num_cells, count, "corr3", out);
            if (num_beams == 4) MatlabMatrix(corr[3], num_cells, count, "corr4", out);
        }

        if( ampIncluded ) {
            MatlabMatrix(amp[0], num_cells, count, "amp1", out);   
            MatlabMatrix(amp[1], num_cells, count, "amp2", out);   
            MatlabMatrix(amp[2], num_cells, count, "amp3", out);
            if (num_beams == 4) MatlabMatrix(amp[3], num_cells, count, "amp4", out);
        }
    }
    MatlabDoubleVector(pressure, count, "pressure", out);
    MatlabDoubleVector(temperature, count, "temperature", out);
    MatlabDoubleVector(heading, count, "heading", out);
    MatlabDoubleVector(pitch, count, "pitch", out);
    MatlabDoubleVector(roll, count, "roll", out);

    MatlabVector(magX, count, "magX", out, 0);
    MatlabVector(magY, count, "magY", out, 0);
    MatlabVector(magZ, count, "magZ", out, 0);

    MatlabDoubleVector(t, count, "time", out);

    MatlabDoubleVector(&cellSize, 1, "cellSize", out);
    MatlabDoubleVector(&blanking, 1, "blanking", out);

    fclose(out);

    exit (0);
}

typedef struct
{
    unsigned short beamData1 :4;
    unsigned short beamData2 :4;
    unsigned short beamData3 :4;
    unsigned short beamData4 :4;
} t_DataSetDescription4Bit;

typedef struct
{
    unsigned int _empty1               :1;
    unsigned int bdScaling             :1;
    unsigned int _empty2               :1;
    unsigned int _empty3               :1;
    unsigned int _empty4               :1;
    unsigned int echoFreqBin           :5;
    unsigned int boostRunning              :1;
    unsigned int telemetryData             :1;
    unsigned int echoIndex                 :4;
    unsigned int activeConfiguration       :1;
    unsigned int lastmeasLowVoltageSkip    :1;
    unsigned int prevWakeUpState           :4;
    unsigned int autoOrient                :3;
    unsigned int orientation               :3;
    unsigned int wakeupstate               :4;
} t_status;

typedef struct
{
    unsigned short  procIdle3   :1;
    unsigned short  procIdle6   :1;
    unsigned short  procIdle12  :1;
    unsigned short  _empty1     :12;
    unsigned short  stat0inUse  :1;
} t_status0;

#define VERSION_DATA_STRUCT_3   3

typedef struct 
{
    unsigned char version;
    unsigned char offsetOfData;
    struct {
        unsigned short pressure         :1;
        unsigned short temp             :1;
        unsigned short compass          :1;
        unsigned short tilt             :1;
        unsigned short _empty           :1;
        unsigned short velIncluded      :1;
        unsigned short ampIncluded      :1;
        unsigned short corrIncluded     :1;
        unsigned short altiIncluded     :1;
        unsigned short altiRawIncluded  :1;
        unsigned short ASTIncluded      :1;
        unsigned short echoIncluded     :1;
        unsigned short ahrsIncluded     :1;
        unsigned short PGoodIncluded    :1;
        unsigned short stdDevIncluded   :1;
        unsigned short _unused          :1;
    } headconfig;
    unsigned int serialNumber;
    unsigned char year;
    unsigned char month;
    unsigned char day;
    unsigned char hour;
    unsigned char minute;
    unsigned char second;
    unsigned short microSeconds100;
    unsigned short soundSpeed;
    short          temperature;
    unsigned int  pressure;
    unsigned short heading;
    short          pitch;
    short          roll;
    union {
        struct {
            unsigned short numCells    :10;
            unsigned short coordSystem :2;
            unsigned short numBeams    :4;
        } beams_cy_cells;
        unsigned short echo_cells;
    };
    unsigned short cellSize;
    unsigned short blanking;
    unsigned char  nominalCorrelation; 
    unsigned char  pressTemp;
    unsigned short battery;
    short          magnHxHyHz[3];
    short          accl3D[3];
    union {
        unsigned short ambVelocity;
        unsigned short echoFrequency;
    };
    t_DataSetDescription4Bit DataSetDescription4bit;   // ushort
    unsigned short transmitEnergy;  
    char           velocityScaling;
    char           powerLevel;
    short          magnTemperature;
    short          rtcTemperature;
    unsigned short error;
    t_status0      status0; // ushort
    t_status       status;  // ulong
    unsigned int  ensembleCounter;
    unsigned char  data[512];
    ///< actual size of the following = 4*nbeams*ncells = 4*4*30
    ///<    int16_t hVel[nBeams][nCells];
    ///<    uint8_t cAmp[nBeams][nCells];
    ///<    uint8_t cCorr[nBeams][nCells];
} OutputData3_t;

// Expected transformation matrixes
// BEAM 124
// 3,3,1.3564,-0.5056,-0.5056,0.0000,-1.1831,1.1831,0.0000,0.5518,0.5518
double beam_124[3][3] = {
    {1.3564,-0.5056,-0.5056},
    {0.0000,-1.1831,1.1831},
    {0.0000,0.5518,0.5518},
};

// BEAM 234
// 3,3,0.5056,-1.3564,0.5056,-1.1831,0.0000,1.1831,0.5518,0.0000,0.5518
double beam_234[3][3] = {
    {0.5056,-1.3564,0.5056},
    {-1.1831,0.0000,1.1831},
    {0.5518,0.0000,0.5518},
};

double beam_ident[3][3] = {
    {1., 0., 0.},
    {0., 1., 0.},
    {0., 0., 1.},
};

// Compares to 3x3 double matrices
// Returns: 0 for equal, 1 for not equal

int
matrix_equal(double *A, double *B) {
    for(int ii = 0; ii < 3; ii++) {
        for(int jj = 0; jj < 3; jj++) {
            if( *(A + ii * 3 + jj) != *(B + ii * 3 + jj)) return 1;
        }
    }
    return 0;
}


int 
main(int argc, char *argv[])
{
    double scale;
    unsigned char buff[65536];
    unsigned char b, n, ii, j, k, id, fam;
    unsigned short i;
    unsigned short sz, ckd, ckh;
    OutputData3_t *ptr;
    short *hVel;
    unsigned short *hEcho;
    unsigned char *cAmp;
    unsigned char *cCorr;
    char *str;
    //double T[3][3];
    double *T;
    double Vxyz[3], V123[3];
    struct tm tm;
    time_t tt;
    int    max_count;
    unsigned char sync;
    long tell;
    char opt;

    count = 0;
    max_count = 1000;

    setenv("TZ", "", 1); // null string is UTC
    tzset();

    while ((opt = getopt(argc, argv, "v")) != -1) {
        switch (opt) {
        case 'v':
            verbose = 1;
            break;
        }
    }
    
    printf("optind:%d, argc:%d\n", optind, argc);

    if ((argc - optind) < 2
        || (out = fopen(argv[argc-1], "wb")) == NULL) {
       
        fprintf(stderr, "ad2cpMAT in1 in2 in3 ... out\n");
        return 1;
    } 

    for (ii = optind ; ii <= argc - 2 ; ii++) {
        if ((fp = fopen(argv[ii], "rb")) == NULL)
            break;

        while(!feof(fp)) {
            if (fread(&sync, 1, 1, fp) != 1)
                break;

            if (sync != 0xa5)
                continue;

            tell = ftell(fp);
            if (fread(&sync, 1, 1, fp) != 1)
                break;

            if (sync != 0x0a)
                continue;

            if (fread(buff, sizeof(unsigned char), 8, fp) != 8)
                break;

            id  = buff[0];
            fam = buff[1];
            sz = *((unsigned short *) &(buff[2]));
            ckd = buff[4] + buff[5]*256;
            ckh = buff[6] + buff[7]*256;    

            if (fread(&buff, sizeof(unsigned char), sz, fp) != sz)
                break;

            if (id == 0xA0) {
                str = strstr(buff, "GETXFAVG");
                n = 0;
                if (str) {
                    double T_tmp[3][3];

                    n = sscanf(str, "GETXFAVG,ROWS=3,COLS=3,M11=%lf,M12=%lf,M13=%lf,M21=%lf,M22=%lf,M23=%lf,M31=%lf,M32=%lf,M33=%lf",
                               &T_tmp[0][0], &T_tmp[0][1], &T_tmp[0][2],
                               &T_tmp[1][0], &T_tmp[1][1], &T_tmp[1][2],
                               &T_tmp[2][0], &T_tmp[2][1], &T_tmp[2][2]);
                    if( n != 9 ) {
                        fprintf(stderr, "WARNING - poorly formed GETXAVG string (%s) - ignoring\n", str);
                    } else {
                        if( !matrix_equal(&T_tmp[0][0], &beam_124[0][0]) ) {
                            if(verbose) printf("GETXFAVG matches beam_124\n");
                        } else if( !matrix_equal(&T_tmp[0][0], &beam_234[0][0]) ) {
                            if(verbose) printf("GETXFAVG matches beam_234\n");
                        } else {
                            fprintf(stderr, "GETXFAVG does not match known beam matrix - confirm this is correct - bailing out\n");
                            return 1;
                        }
                    }
                }
            }
		
            else if (id == 0x1c || id == 0x15 || id == 0x16) { // echo, burst data or average data record
                ptr = (OutputData3_t *) buff;
                cellSize = ptr -> cellSize / 1000.; //mm - pg62 N3015-007-Integrators-Guild-AD2CP.pdf
                blanking = ptr -> blanking / 100.;  //cm - pg62 N3015-007-Integrators-Guild-AD2CP.pdf
                    
                scale = pow(10.0, ptr -> velocityScaling);

                if (count == 0) {
                    if (id == 0x1c) {
                        num_cells = ptr -> echo_cells;
                        num_beams = 1;
                        if( (echo = Darray(num_cells, max_count)) ) {
                            if(verbose) printf("alloc ok: %d x %d\n", num_cells, max_count);
                        } else {
                            fprintf(stderr, "alloc faild: %d x %d\n", num_cells, max_count);
                            return 1;
                        }

                        beamN = vector(max_count);
                        power = vector(max_count);
                    }
                    else {
                        num_cells = ptr -> beams_cy_cells.numCells;
                        num_beams = ptr -> beams_cy_cells.numBeams;

                        for (j = 0 ; j < 4 ; j++) {
                            beamv[j] = Darray(num_cells, max_count);
                            corr[j] = array(num_cells, max_count);
                            amp[j] = array(num_cells, max_count);
                        }
                    }
                    t           = Dvector(max_count);
                    pressure    = Dvector(max_count); 
                    pitch       = Dvector(max_count); 
                    roll        = Dvector(max_count); 
                    heading     = Dvector(max_count); 
                    temperature = Dvector(max_count); 

                    magX        = vector(max_count); 
                    magY        = vector(max_count); 
                    magZ        = vector(max_count); 
                }

                pressure[count]    = ptr -> pressure*0.001;
                temperature[count] = ptr -> temperature*0.01;
                heading[count]     = ptr -> heading*0.01;
                pitch[count]       = ptr -> pitch*0.01;
                roll[count]        = ptr -> roll*0.01;
                magX[count]        = ptr -> magnHxHyHz[0]; 
                magY[count]        = ptr -> magnHxHyHz[1];
                magZ[count]        = ptr -> magnHxHyHz[2];

                tm.tm_year = ptr -> year;
                tm.tm_mon  = ptr -> month;
                tm.tm_mday = ptr -> day;
                tm.tm_hour = ptr -> hour;
                tm.tm_min  = ptr -> minute;
                tm.tm_sec  = ptr -> second;
                tm.tm_isdst = 0;
                tt = mktime(&tm);
        
                t[count] = tt + ptr -> microSeconds100/1e4;

                //printf("B0=%d B1=%d B2=%d B3=%d\n",
                //       ptr -> DataSetDescription4bit.beamData1, ptr -> DataSetDescription4bit.beamData2,
                //       ptr -> DataSetDescription4bit.beamData3, ptr -> DataSetDescription4bit.beamData4);

                if(  ptr -> DataSetDescription4bit.beamData1 == 1 && ptr -> DataSetDescription4bit.beamData2 == 2
                     && ptr -> DataSetDescription4bit.beamData3 == 4 && ptr -> DataSetDescription4bit.beamData4 == 0) {
                    if(verbose) printf("Using beam_124 transformation\n");
                    T = &beam_124[0][0];
                } else if ( ptr -> DataSetDescription4bit.beamData1 == 2 && ptr -> DataSetDescription4bit.beamData2 == 3
                            && ptr -> DataSetDescription4bit.beamData3 == 4 && ptr -> DataSetDescription4bit.beamData4 == 0) {
                    if(verbose) printf("Using beam_234 transformation\n");
                    T = &beam_234[0][0];
                } else {
                    if (num_beams == 3) {
                        fprintf(stderr, "WARNING - unknown beam configuration %d:%d:%d:%d - using identity matrix\n",
                                ptr -> DataSetDescription4bit.beamData1, ptr -> DataSetDescription4bit.beamData2,
                                ptr -> DataSetDescription4bit.beamData3, ptr -> DataSetDescription4bit.beamData4 );
                        T = &beam_ident[0][0];
                    } else {
                        if(verbose) printf("num_beams:%d - no transformations being applied\n", num_beams);
                    }
                }
                if (id == 0x15 || id == 0x16) {
                    hVel = (short *) ptr -> data;
                    cAmp = ptr -> data + 2*ptr -> beams_cy_cells.numCells*ptr -> beams_cy_cells.numBeams;
                    cCorr = cAmp + ptr -> beams_cy_cells.numCells*ptr -> beams_cy_cells.numBeams;
                    for (i = 0 ; i < ptr -> beams_cy_cells.numCells ; i ++) {
                        if (ptr -> beams_cy_cells.numBeams != 3) {
                            for (j = 0 ; j < ptr -> beams_cy_cells.numBeams ; j ++) {
                                beamv[j][i][count] = hVel[j*ptr -> beams_cy_cells.numCells + i];
                            }
                        } else {
                            for (j = 0 ; j < ptr -> beams_cy_cells.numBeams ; j ++) {
                                V123[j] = scale*hVel[j*ptr -> beams_cy_cells.numCells + i];
                            }
                            for (j = 0 ; j < ptr -> beams_cy_cells.numBeams ; j ++) {
                                Vxyz[j] = 0;
                                for (k = 0 ; k < ptr -> beams_cy_cells.numBeams ; k ++) {
                                    //Vxyz[j] += T[j][k]*V123[k];
                                    Vxyz[j] += *(T + j * 3 + k) * V123[k];
                                }
                                beamv[j][i][count] = Vxyz[j];
                            }
                        }
                        for (j = 0 ; j < ptr -> beams_cy_cells.numBeams ; j ++) {
                            amp[j][i][count] = cAmp[j*ptr -> beams_cy_cells.numCells + i];
                        } 
                        for (j = 0 ; j < ptr -> beams_cy_cells.numBeams ; j ++) {
                            corr[j][i][count] = cCorr[j*ptr -> beams_cy_cells.numCells + i];
                        } 
                    }  
                }
                else if (id == 0x1c) {
                    power[count] = ptr -> powerLevel;
                    beamN[count] = ptr -> DataSetDescription4bit.beamData1;
                    hEcho = (unsigned short *) ptr -> data;
                    if( verbose ) printf("nc = %d\n", num_cells);	
                    for (i = 0 ; i < num_cells ; i++) {
                        echo[i][count] = hEcho[i] * 0.01; 
                    }
                }
                count ++;
                if( verbose ) printf("count = %d\n", count);
            }
        }
        fclose(fp);
    }  
    WriteMatlab (argv[argc-1], ptr -> headconfig.ampIncluded, ptr -> headconfig.corrIncluded);

    return 0;      
}

