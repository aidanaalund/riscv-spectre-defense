# RISC-V Spectre Defense Project

## Authors: Aidan Aalund, Logan Bristol, Andres Wearden

## Description

This repository contains source code for our course project for **ECE 382N-Sec: Security at the HW/SW Interface** (taught by Dr. Neil Zhao). The project aims to review defenses to Spectre-class vulnerabilities for common research and commercial RISC-V microprocessors. SonicBOOM (Zhao et al.) and the SiFive P870 (SiFive, Inc.) were selected as representative examples. Within the gem5 microarchitectural simulator, two configurations for `o3cpu` are created to model the processors from publicly available documentation. We implement RISC-V versions of x86-64 Spectre defenses such as the `lfence` instruction, [speculative privacy tracking](https://github.com/FPSG-UIUC/SPT) (SPT) (Choudhary et al.), and [Delay on Miss + Value Prediction](https://dl.acm.org/doi/10.1145/3307650.3322216) (Sakalis et al.). Benchmarks will validate functionality and performance in application-level scenarios.

## How to use

Coming soon!
