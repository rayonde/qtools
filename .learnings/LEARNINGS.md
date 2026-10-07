# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20261007-001] correction

**Logged**: 2026-10-07
**Priority**: medium
**Status**: pending
**Area**: backend

### Summary
TEC CSV 日志需要同时记录设定温度和实际温度。

### Details
用户澄清了 CSV 数据格式为 `timestamp,tec.settemp,tec.temp`；第二列读取目标设定值，第三列读取实际测量值。

### Suggested Action
实现 TEC CLI 时，CSV 每行应按 `timestamp,tec.settemp,tec.temp` 写入；不要丢失设定温度或实际温度中的任一列。

### Metadata
- Source: user_feedback
- Related Files: src/qtools/tec/cli.py
- Tags: tec, csv, setpoint

---

## [LRN-20261006-001] correction

**Logged**: 2026-10-06
**Priority**: high
**Status**: pending
**Area**: backend

### Summary
多维 OAM tomography 必须与原有 qubit tomography 实现隔离。

### Details
用户明确要求不要修改原来的 `tomography/TomoClass.py`、`TomoFunctions.py` 等文件；新功能应只放在 `qtools.tomo.oam` 子包中。

### Suggested Action
恢复原 tomography 文件，使用独立的 OAM tomography 类和内部 MLE 实现。

### Metadata
- Source: user_feedback
- Related Files: src/qtools/tomo/oam
- Tags: oam, tomography, isolation

---
