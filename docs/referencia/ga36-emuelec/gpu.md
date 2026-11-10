# GPU (Mali-400 MP2) on the GA36-MB V1.2: what the factory firmware and our kernel say

Read on 2026-11-10 from the factory image (`R36S GA36-MB V1.2-20260416 - Emuelec - No ROMS.img`,
the one in `R36OS_GA36_FACTORY`) and from our compiled DTB (`out/ga36/kernel/dtbs/`).
Nothing here was measured on the device; it is what the files declare.

## 1. The EmuELEC project never controlled the GPU

Its scripts only touch the **CPU** (`maxperf`/`normperf` write `performance`/`ondemand` to
the governor; `cpu-ondemand-tune` sets the `ondemand` tunables) and the **DRAM** devfreq
(`sunxi-ddrfreq/devfreq/sunxi-ddrfreq/dsm/scene`). No script reads or writes a GPU clock.
Whatever the GPU did on the original system was decided inside the vendor kernel.

## 2. Factory firmware (vendor kernel Linux 3.4.39, Allwinner BSP)

Decoded from the binary `script.bin` (FEX) in the boot area of the image:

```
[mali_para]
  mali_used         = 1
  mali_clkdiv       = 1
  mali_extreme_freq = 408     ; MHz, the highest GPU clock the firmware allows
  mali_extreme_vol  = 1100    ; mV, the voltage for that clock
```

- The GPU maximum is **408 MHz at 1.10 V**. The factory PMIC log shows `dcdc2` at 1100 mV
  (see the regulator table in `README.md`), which matches: the GPU sits on that rail.
- The kernel has a `cpu_budget_cooling` driver whose state table is
  `c0limit / c0nr / c1limit / c1nr / gputhrottle`: temperature limits the CPU clusters
  **and the GPU together** (`gputhrottle`). The thresholds are the ones in `README.md`
  (75 C and 90 C active, 110 C critical).
- The userspace GPU stack is the proprietary `libMali.so` with `mali.ko` (vermagic 3.4.39,
  parameters: `mali_max_job_runtime`, `mali_max_pp_cores_group_1`, `mali_l2_max_reads`,
  memory sizes). The vendor GPU DVFS algorithm is inside that driver and was **not** read.

## 3. Our kernel (mainline, `lima` driver)

From the compiled DTB (`sun8i-a33-ga36-mb-v1.2-panel1.dtb`) and the built `.config`:

| Item | Value |
|---|---|
| GPU node | `gpu@1c40000`, `arm,mali-400`, `assigned-clock-rates = 384000000` (boot rate) |
| OPP table (`opp-table-gpu`) | 144, 240 and 384 MHz, **no voltages** |
| GPU regulator (`mali-supply`) | none declared; `dmesg`: `_opp_set_regulators: no regulator (mali) found` |
| devfreq governor | `simple_ondemand` (the only devfreq governor built; `performance`, `powersave`, `userspace` are off) |
| GPU cooling | node has `#cooling-cells`; thermal maps use GPU states 1 and 2 at `gpu-alert0` (85 C passive) and `gpu-alert1` (95 C hot) |
| `CONFIG_DEVFREQ_THERMAL` | **not set**, so the cooling device is never registered (`Failed to register cooling device`) and the two GPU trips do nothing |
| CPU trips | `cpu-alert0` 75 C, `cpu-alert1` 90 C, `cpu-crit` 110 C (these do work: `cpufreq` cooling) |

## 4. What follows from it

- 384 MHz is inside the envelope the factory firmware validated (408 MHz at 1.10 V), and it
  is the clock the GPU has at boot.
- Without the GPU thermal cooling, the GPU is not throttled by temperature. If heat becomes
  a concern, enable `CONFIG_DEVFREQ_THERMAL`.
- **The GPU clock is not the cause of the freeze at game start.** A build that pinned the
  GPU at 384 MHz (`gpu_mhz=384` in every trace sample) froze the same way, so the pin
  (`r36os-gpu`) was removed. What the trace shows instead is in task 9.8: the display
  controller (`lcd-controller`) stops generating vblank after the process swap.

## 5. How to reproduce

- FEX: extract the boot area (`dd bs=1M count=116`) and decode the sunxi script with a
  parser for the head `{main_cnt, version[3]}`, sections `{name[32], length, offset_words}`
  and items `{name[32], offset_words, pattern = type<<16 | words}`.
- Vendor module: `modinfo mali.ko` after extracting `usr/lib/modules/mali.ko` from the
  `SYSTEM` squashfs (inside the FAT16 `EMUELEC` volume, partition 7).
- DTB: `dtc -I dtb -O dts` (available in the `localhost/r36os-cross` image).
