build-gem5:
	scons build/RISCV/gem5.opt -j4

run-baseline:
	python3 configs/riscv/o3_system.py --defense baseline

run-all-defenses:
	python3 scripts/batch_runner.py
