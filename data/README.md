# NOAA sonar replay data

The local file `raw/noaa-sh1305-18khz.csv` is the NOAA NCEI public processed
water-column sonar recording used by the demo.

- Archive: [NOAA NCEI Water-Column Sonar Data Archive](https://cires.gitbook.io/ncei-wcsd-archive/master.md)
- Cruise: SH1305, Bell M. Shimada
- Instrument: Simrad EK60, 18 kHz
- Recording segment: May 23, 2013, approximately 08:08–09:12 UTC
- Download size: 30,308,969 bytes; 2,545 valid pings (three empty/invalid rows skipped)
- SHA-256: `146265b42148044e5f7b76583e783377d820639f16b6c916ba4ce47e0a6498c4`
- Direct file: [NOAA NCEI CSV](https://ncei-wcsd-archive.s3-us-west-2.amazonaws.com/data/processed/SH1305/18kHz/SaKe2013-D20130523-T080854_to_SaKe2013-D20130523-T085643.csv)

The data are unlabeled acoustic echogram samples, not labeled ghost-net or
marine-debris observations. This fisheries water-column recording can
demonstrate replay and acoustic outlier scoring, but it does not validate
seafloor debris detection. Refer to NOAA's archive and cruise citation
information before redistributing or publishing results.

Download or restore this file with `npm run setup:data`.

`npm run setup` preprocesses this source and writes a chronological train,
validation, and held-out test split under `data/splits/`. Ten pings between
partitions are embargoed to reduce leakage from adjacent ping sequences.
