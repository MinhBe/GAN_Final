# Restore `waf_probe_results.csv`

The original CSV is distributed as lossless ZIP parts so every Git blob stays
below 95 MB. Verify the parts against `waf_probe_results.csv.zip.sha256`, join
them in numeric order, then extract the ZIP.

On Windows Command Prompt:

```bat
copy /b waf_probe_results.csv.zip.part001 waf_probe_results.csv.zip
tar -xf waf_probe_results.csv.zip
```

If the manifest lists more parts, append them to the `copy /b` command in
numeric order. The extracted `waf_probe_results.csv` is byte-identical to the
local source that was packaged.
