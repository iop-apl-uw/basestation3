# Seaglider Basestation Development Guide

Quick and dirty instructures for checking in changes to the basestation

## Get a copy of the repo

I create a directory structure of:

```~/work/git```

to contain all my ```git``` related repos.  Instructions below assume that setup.

Make sure you have git installed.  For the Mac, I aways run out of ```brew``` to make sure I'm getting more contemporary binaries.

If you haven't already setup an SSH key for use on git, so do now.  

I always use ```~/.ssh/config``` for specifying the private key.

Clone a copy of repo from git:

```cd ~/work/git```
```git clone git@github.com:iop-apl-uw/basestation3.git```

As an alternative, you can specify the key on the command line:

```GIT_SSH_COMMAND="ssh -i /path/to/your/private_key" git clone git@github.com:iop-apl-uw/basestation3.git```

## Install python and the basestation packages with UV for development

### Install UV
Install [uv](https://github.com/astral-sh/uv):
```curl -LsSf https://astral.sh/uv/install.sh | sh```
More detailed instructions can be found in the [uv documentation](https://docs.astral.sh/uv/).

This should result in a binary installed in ```~/.local/bin/uv```.  This directory may need to be added to your ```$PATH```.

### Setup the virtual environment

From the ```~/work/git/basestation3``` directory, pull down python and the packages:

```uv sync --all-extras```

This will create a sub-directory:

```~/work/git/basestation3/.venv```

That is the virtual environment - its the equivilent of ```/opt/basestation``` on the servers.

## Development cycle

There are two ways of ensuring you get the correct python and packages while doing development.  Easiest is to activate the virtual environment:

```source ~/work/git/basestation3/.venv/bin/activate```

in a shell.  Now, when you run ```python```, you will get the python in ```~/work/git/basestation3/.venv/bin/python``` and asscociated packages.  As an alternative you can run:

```uv run Base.py --help``` 

but you need to be in the ```~/work/git/basestation3``` directory.

### Test out your setup

From ```~/work/git/basestaiton3``` run ```make rufflint``` followed by ```make test```.  ```make``` may not be installed on your system - ```brew``` is the way to go for installing that.

### General flow

Once a bug has been located, make the needed code changes.  I find running ```make rufflint``` is a really good way to check for syntax issues, mis-spellings, etc.  From there, test the specific aspect of the fix - this will often mean running some really small subset of the basestation code.  I don't have a cheat sheet of all those worked up - probably just adding to this document is the best approach.

After testing the specific fix, adding a specific test case (often referred to as a regression) is a good idea.  Note: This is not followed nearly often enough.

Before checkin, run ```make test``` and ensure there are no additional errors.

Checking in involves staging the change, the committing it:

```git add <updated_file>```
```git commit -m 'Commit comment'```

Finally push the commit:

```git push origin master```

On commit, the ```CI``` process will be run on git - any issues will be reported to your email inbox
