# Vendored chan.py calculation core

Source: https://github.com/Vespa314/chan.py
Commit: f8ca3b5e44d7166e2abd756a8e7fa816c79faebe
License: MIT, original LICENSE retained in this directory.

Only Python calculation modules in Bi, BuySellPoint, ChanModel, Combiner,
Common, KLine, Math, Seg, ZS and ChanConfig.py are included.
No private strategy/ML components or network data providers are used.

Mechanical compatibility changes:
- Absolute imports are prefixed with quant.vendor.chanpy.
- Postponed annotations are enabled for the host Python 3.9 runtime.
- typing.Self imports are provided by typing_extensions.
- Empty package initializer added.

Calculation algorithms are unchanged. Platform integration is in quant/chan_events.py.
The experiment snapshot records upstream commit, replay configuration and platform
code hash. Update adapter version and rerun replay invariance tests when upgrading.
