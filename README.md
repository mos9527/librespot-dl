# Project Name
librespot-dl

## Installation
```
pip install git+https://github.com/mos9527/librespot-dl
```

## Usage
```
librespot-dl -h
(or python -m librespot_dl -h)

options:
  -h, --help            show this help message and exit
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Logging Level

Authentication:
  --load LOAD           Load credentials from file
  --save SAVE           Save credentials to file
  --email EMAIL         Spotify account email address
  --password PASSWORD   Spotify account password

Download Options:
  --template TEMPLATE, -t TEMPLATE
                        Output filename template.
                         Avaialble ones are:
                                {title},{artist},{albumartist},{album},{tracknumber},{date},{copyright},{discnumber}
  --output OUTPUT, -o OUTPUT
                        Output directory
  --quality {BEST,WORST}
                        Audio quality
  url                   Spotify track/album/playlist URL
```

## Potential DRM Violations
Please note that this project does not support or condone any form of DRM violations. It is important to respect intellectual property rights and adhere to legal and ethical standards when using this software.
