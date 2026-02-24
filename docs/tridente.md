# RBR Tridente Proposed Naming convention

## Summary of offerings

This table outlines all the advertised channels available for a Tridente.

| Channel       | Abbr | Wavelength nm (Excitation) | WaveLength nm (Emission) |
|:--------------|------|:---------------------------|:-------------------------|
| Chlorophyll a | chla | 470                        | 695                      |
| Chlorophyll a | chla | 435                        | 695                      |
| fDOM          | fdom | 365                        | 450                      |
| Phycocyanin   | pc   | 590                        | 654                      |
| Phycoerythrin | pe   | 525                        | 600                      |
| Rhodamine     | rd   | 550                        | 600                      |
| Fluorescein   | fitc | 470                        | 660                      |
| Backscatter   | bb   | 470                        |                          |
| Backscatter   | bb   | 525                        |                          |
| Backscatter   | bb   | 650                        |                          |
| Backscatter   | bb   | 700                        |                          |
| Turbidity     | tu   | 650                        |                          |
| Turbidity     | tu   | 700                        |                          |

Notes:
- Abbreviation are as close to the RBR abbreviations, where available.
- When there is no value in the Emission column, the Excitation column contains the channels wavelength

## Assumptions
1. The naming convention should support multiple Tridentes installed on a single glider (be they on truck or on the scicon)
2. No single Tridente will have multiple channels of the exact same type (i.e. to backscatter channels both of wavelength 470nm).  *Note: This assumption is a core to the basestation operation and not specific to the Tridente.  It is placed here for clarity.*
3. A single "master scicon.ins" file could be constructed that contains definitions for every version of the Tridente that could be purchased. 

## Proposed naming

### Channel names

A channel is name by combining the channel `Abbr` and the (Excitation) `Wavelength`.  For exmaple:

- 470nm backscatter - `bb470`
- Chlorophyll a 430 excitation - `chla470`

### Instrument name

`tridente[instnum]chan1chan2chan3`

where:
- `[instnum]` is an optional single digit in the range of `1 - 9`.
- `chan[1-3]` is a channel name from above.

Note: Not supplying `[instanum]` and an instance number of `1` should be considered synonymous.  It is possible that some of the basestation code paths may treat these as distinct, that should not be assumed or depended on.

For example, a typical 700nm and 470nm backscatter and 470nm Chlorophyll a would be:

`tridentebb700bb470chla470`

or

`tridente1bb700bb470chla470`

A second instrument of the exact same configuration on the glider would be:

`tridente2bb700bb470chla470`

## Scicon Files

A `scicon.ins` entry for this instrument would be:

```
tridentebb700bb470chla470 = {
   prefix = td
   baud = 19200
   cycles = 0
   timeout = 1000
   warmup = 0
   skip = 0
   terminator = 10
   meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
   format = %d, %00, %01, %02
   column = bb700(100000,0)
   column = bb470(100000,0)
   column = chla470(1000,0)
}
```

A typical `scicon.att`:
```
tridente = {
    type = tridentebb700bb470chla470
    hwchan = 1
}
```

A typical `scicon.sch`:

```
tridente = {
   100, 5
   250, 10
   1000, 60
}
```

## Truck files

A `.cnf` file would need to be generated that matched the channel output format. From the above example, 

```
prefix = tridentebb700bb470chla470
name = tridentebb700bb470chla470
baud = 19200
timeout = 1000
warmup = 0
terminator = 10
meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
format = %d, %00, %01, %02
column = bb700(100000,0)
column = bb470(100000,0)
column = chla470(1000,0)
```

## Basestation processing

A new basestation sensor extension will be written for the Tridente data, mainly to handle adding the needed netcdf metadata for each particular channel.  There should be no need to modify the `scicon_ext.py` extension. Names in the per-dive netcdf file will be of the normal form `instrument_channel` - so, from the above example `tridentebb700bb470chla470_bb470` would be the name of the backscatter 470 channel on instrument `tridentebb700bb470chla470`. 

A new basestation plotting extension will be written for the Tridente data.  Given the regular nature of the above naming scheme, the channel specifications in the instrument name should be largely ignorable and the code data driven off the channel name - much the same was the current WetLabs plotting code works.

## Alternative Approach - approach rejected.

If assumption 3 from above is dropped, then the `scicon.ins` (or glider truck `.cnf` file) would need to be customized on a per-glider basis.  The only requirement for the basestation code is a consistent approach to the instrument naming is adhered to - for example, the name starts with `tridente` and follows with a `1` or `2`.

### Scicon files

A `scicon.ins` entry for two instruments would be:

```
tridente1 = {
   prefix = td
   baud = 19200
   cycles = 0
   timeout = 1000
   warmup = 0
   skip = 0
   terminator = 10
   meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
   format = %d, %00, %01, %02
   column = bb700(100000,0)
   column = bb470(100000,0)
   column = chla470(1000,0)
}

tridente2 = {
   prefix = td
   baud = 19200
   cycles = 0
   timeout = 1000
   warmup = 0
   skip = 0
   terminator = 10
   meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
   format = %d, %00, %01, %02
   column = tu650(100000,0)
   column = tu700(100000,0)
   column = chla470(1000,0)
}
```

A typical `scicon.att`:
```
tridente1 = {
    type = tridente1
    hwchan = 1
}
tridente2 = {
    type = tridente2
    hwchan = 2
}
```

A typical `scicon.sch`:

```
tridente1 = {
   100, 5
   250, 10
   1000, 60
}
tridente2 = {
   100, 5
   250, 10
   1000, 60
}
```

## Truck files

A `.cnf` file would need to be generated that matched the channel output format, with the same naming scheme. From the above example, 

```
prefix = tridente1
name = tridente1
baud = 19200
timeout = 1000
warmup = 0
terminator = 10
meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
format = %d, %00, %01, %02
column = bb700(100000,0)
column = bb470(100000,0)
column = chla470(1000,0)
```

