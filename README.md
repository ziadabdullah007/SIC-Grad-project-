# Real-Time AI Server Telemetry: Streaming Data Processing & Analytics

**An End-to-End Big Data Engineering Platform for GPU Infrastructure Monitoring and Analytics**

**Samsung Innovation Campus – Big Data Course**

---

## 1. Project Overview

An end-to-end Data Engineering project designed to help enterprises evaluate GPU server configurations for AI image-generation workloads.

The platform combines real-time streaming and batch processing to ingest, transform, validate, and analyze server telemetry data, providing insights into resource utilization, power efficiency, thermal behavior, and infrastructure costs.

It also includes **DC Risk Lab**, an interactive platform that extends the project's analytical capabilities through server exploration, risk assessment, what-if simulation, and LLM-powered explanations.

## 2. Business Problem & Objectives

An enterprise needs to identify the most suitable GPU server configurations for deploying an AI image-generation application.

The project analyzes operational telemetry to compare five GPU configurations and support informed infrastructure selection decisions.

**Main Objectives:**
- Build a streaming and batch data processing platform.
- Process and analyze over 2 million telemetry records.
- Implement data quality and validation.
- Design a Star Schema Data Warehouse.
- Develop interactive dashboards and infrastructure analytics tools.
- Identify promising server configurations for deployment evaluation.

## 3. Dataset Overview

- **Records:** 2,000,000
- **Columns:** 26
- **GPU Configurations:** 5
- **Observation Period:** 278 days

| Server ID | GPU Configuration |
|---|---|
| S001 | NVIDIA A100 |
| S002 | NVIDIA L40S |
| S003 | AMD MI300X |
| S004 | NVIDIA H100 |
| S005 | NVIDIA B200 |

Telemetry metrics include GPU and CPU utilization, memory usage, power consumption, temperature, and cooling-related measurements.

## 4. System Architecture

<img width="1280" height="640" alt="WhatsApp Image 2026-10-29 at 15 08 07" src="https://github.com/user-attachments/assets/7a29af32-783d-4c8a-940f-78be37da9842" />


The solution integrates cloud-based ingestion, streaming and batch processing, layered data storage, data warehousing, and business intelligence.

## 5. Technologies Used

| Category | Technologies |
|---|---|
| Programming | Python, SQL |
| Data Ingestion | Azure Event Hubs |
| Cloud Storage | Azure Data Lake Storage Gen2 |
| Storage Formats | Parquet, Delta Lake |
| Stream Processing | Apache Spark Structured Streaming, Kafka Connector |
| Data Processing | PySpark, Spark SQL |
| Data Platform | Microsoft Fabric |
| Data Warehousing | Star Schema, Fabric Warehouse |
| Automation & Streaming Analytics | Fabric Data Pipelines, Eventstream, Eventhouse, KQL |
| Visualization | Power BI, DAX |
| Application | Python Backend, Web Frontend |
| AI Integration | Large Language Models (LLMs) |
| Deployment | Render |

## 6. Key Deliverables

### Data Engineering Pipeline

- Python-based telemetry producer.
- Azure Event Hubs for streaming ingestion.
- ADLS Gen2 Bronze storage.
- Streaming and batch processing.
- Data validation, duplicate handling, and Dead Letter Queue (DLQ).
- Lakehouse architecture with Bronze, Silver, and Gold layers.
- Star Schema Data Warehouse.

### Power BI Dashboard

Four analytical pages:

- Overview
- Efficiency & Power
- Thermal & Cooling
- AI Workload

### DC Risk Lab – Interactive Platform

An interactive Data Center Intelligence Platform developed as an extension of the main project.

**Key Features:**
- **Server Explorer:** Explore GPU server configurations and historical telemetry.
- **What-if Simulator:** Evaluate hypothetical operating scenarios.
- **Risk Assessment:** Identify potential operational risks using historical baselines and hardware specifications.
- **AI Risk Analyst:** Generate LLM-powered explanations based on analytical findings.
- **Reports:** Access structured analytical reports.

**Access the Platform:** [DC Risk Lab](https://sic-grad-project-1.onrender.com/)

*Note: DC Risk Lab uses historical telemetry baselines, documented hardware rules, rule-based analytics, and LLM-generated explanations. It does not use a trained ML model or produce hardware failure probabilities. What-if scenarios are analytical evaluations, not physical hardware simulations.*

## 7. Key Findings & Recommendations

The analysis highlighted differences across the five GPU configurations in resource utilization, power efficiency, thermal behavior, and infrastructure costs.

Two configurations were shortlisted for further consideration:

- **S002 – NVIDIA L40S:** A cost-conscious candidate with promising observed power-efficiency characteristics.
- **S005 – NVIDIA B200:** A higher-cost configuration with higher observed average GPU utilization.

Further benchmarking under comparable AI workload conditions is recommended before making the final deployment decision.

## 8. Documentation & Acknowledgments

For detailed implementation steps, architecture explanations, data processing workflows, and analytical results, refer to the project's documentation.

Developed as part of the **Samsung Innovation Campus Big Data Course**.

Special thanks to our instructor, facilitators, organizers, and teammates for their guidance, support, and collaboration.

---

**Project:** Real-Time AI Server Telemetry: Streaming Data Processing & Analytics

**Program:** Samsung Innovation Campus – Big Data Course

**Interactive Platform:** [DC Risk Lab](https://sic-grad-project-1.onrender.com/)
