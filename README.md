# torch-zomboid
Python application to generate Lua type stubs for *Project Zomboid*'s modding API. It can also be used to generate or
update Rosetta files. It should work and be accurate on any game version b42+, and likely works for b41 too.

## Usage
Basic usage to generate EmmyLua stubs:
```commandline
py src/umbrella/torchzomboid/cli.py emmylua "D:/Program Files (x86)/Steam/steamapps/common/ProjectZomboid" "D:/torch_out"
```
To get details on available options, launch with `-h`.
```commandline
py src/umbrella/torchzomboid/cli.py -h
```

## Dependencies
torch-zomboid requires [torch](https://github.com/demiurgeQuantified/torch) installed and on the python module path.
