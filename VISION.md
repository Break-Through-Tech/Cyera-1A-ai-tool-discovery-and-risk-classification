# AI Tool Discovery & Risk Classification

## 1. End-to-End Vision

The goal of this project is to build a prototype system that gives an enterprise visibility into the AI tools being used across the organization and helps security or governance teams understand which tools may require attention.

The easiest way to think about the project is as the following pipeline:

**Enterprise activity data → Tool discovery → AI identification → Tool classification → Risk assessment → Governance insights**

### Example

Imagine the system receives enterprise activity showing:

* Multiple Engineering employees accessing `cursor.com`
* Marketing employees accessing `jasper.ai`
* Finance employees accessing an unfamiliar application called `example-ai-tool.com`
* Employees also accessing ordinary SaaS applications such as Slack, Salesforce, and Notion

The system should be able to answer:

1. Which applications in this data are AI-related?
2. What type of AI tool is each one?
3. Which employees or departments are using them?
4. Is the tool already known or approved?
5. What characteristics of the tool could create governance concerns?
6. Why did the system assign that risk level?
7. What trends or potentially interesting behavior should a governance/security analyst investigate?

The final product should feel like a lightweight **AI usage discovery and governance console**, rather than simply an ML classification notebook.

---

# 2. Proposed System Architecture

The system can be divided into five major components.

## Component 1 - Enterprise Activity Ingestion

The system receives synthetic enterprise usage data representing how employees interact with applications.

Possible sources include:

* Browser activity
* Network/domain activity
* SaaS application usage
* Login/application events
* Department or employee metadata

For this project, all enterprise activity data can be synthetic.

The goal is not to replicate a specific production logging system, but to create realistic enough data to demonstrate the discovery workflow.

---

## Component 2 - AI Tool Discovery

The first problem is determining whether an observed application is an AI tool.

For example:

`cursor.com` → AI tool

`chatgpt.com` → AI tool

`salesforce.com` → not primarily an AI tool

`unknown-ai-startup.com` → potentially AI, even if the tool was not present in the original training dataset

You can explore several techniques here, including:

* Known tool/domain matching
* NLP classification based on product descriptions
* Embedding similarity
* Semantic search
* Clustering
* Classification models
* LLM-based classification

One important goal is to avoid creating a system that works only as a static lookup table.

Ideally, the system should be capable of reasoning about a **previously unseen application** using information such as its name, domain, description, category, and other metadata.

---

## Component 3 - AI Tool Categorization

Once an application has been identified as AI-related, the system should classify its business purpose.

An initial taxonomy could include categories such as:

* Coding / Developer Tools
* General AI Assistants
* Content Generation
* Image / Video Generation
* Meeting / Transcription Tools
* Data Analytics
* Customer Support
* Sales / Marketing
* Productivity
* Research / Search
* AI Infrastructure / Model Platforms
* Other

The exact taxonomy can evolve during the project.

The important objective is that the system produces a meaningful category that can later be used for analytics and governance.

---

## Component 4 - Governance Risk Assessment

The system should then evaluate the application against a set of governance criteria.

The goal is **not** to build a mathematically perfect universal cybersecurity risk score.

Instead, the goal is to demonstrate how tool metadata and enterprise usage context could be combined into an explainable governance assessment.

Example factors could include:

* Whether the tool is approved or unapproved
* Whether the vendor offers enterprise security controls
* Whether SSO/SAML is available
* Whether submitted data may be used for model training
* Data retention policies
* Availability of administrative controls
* Type of data likely to be submitted
* Number of employees using the application
* Departments using the application
* Whether sensitive departments are using it
* Growth in usage over time
* Whether the application is newly discovered

The important requirement is **explainability**.

Instead of producing:

**Risk: High**

the system should ideally produce something such as:

**Risk: High**

Reasons:

* Tool is not on the approved AI application list
* Tool is being used by Finance employees
* Vendor metadata indicates submitted content may be retained
* No enterprise SSO capability was identified

The precise risk model is something the team can design and justify.

---

## Component 5 - Governance Investigation Experience

The final layer should allow a security or governance analyst to explore the results.

This could include a simple dashboard showing:

* Total AI applications discovered
* Approved vs. unapproved AI applications
* AI tools by category
* AI tools by department
* Highest-risk applications
* Most-used AI applications
* Newly discovered applications
* AI usage trends over time

The application should also support investigation of an individual tool.

For example:

**Cursor**

Category: Coding Assistant

Users: 47

Primary Department: Engineering

Approval Status: Approved

Governance Risk: Medium

Reasons: Source code may be submitted to the service; enterprise controls available; tool is approved.

Optionally, the application can provide a natural-language interface where an analyst could ask questions such as:

* "Which unapproved AI tools are being used by Finance?"
* "What are the highest-risk AI tools in Engineering?"
* "Which new AI applications appeared this month?"
* "Why was Tool X marked high risk?"
* "Which generative AI applications are growing fastest?"

The technical implementation of this interface is flexible.

It could use RAG, structured querying, tool calling, SQL generation, or a combination of approaches.

---

# 3. Synthetic Data Schema

The project should use at least two logical datasets.

## Dataset A - Enterprise Application Activity

This represents application usage inside a fictional company.

Suggested schema:

| Field                      | Description                        | Example                |
| -------------------------- | ---------------------------------- | ---------------------- |
| `event_id`                 | Unique activity event              | `evt_001234`           |
| `timestamp`                | Time of activity                   | `2026-09-15T14:32:00Z` |
| `employee_id`              | Synthetic employee identifier      | `emp_0182`             |
| `department`               | Employee department                | `Engineering`          |
| `job_role`                 | Optional synthetic role            | `Software Engineer`    |
| `application_name`         | Detected application               | `Cursor`               |
| `domain`                   | Application domain                 | `cursor.com`           |
| `event_type`               | Type of activity                   | `browser_visit`        |
| `session_duration_seconds` | Optional usage duration            | `420`                  |
| `bytes_uploaded`           | Optional simulated upload volume   | `250000`               |
| `bytes_downloaded`         | Optional simulated download volume | `1200000`              |
| `device_type`              | Optional device context            | `MacOS`                |

The minimum useful fields are:

`timestamp`, `employee_id`, `department`, `application_name`, and `domain`.

The additional fields can support more advanced analysis.

---

## Dataset B - AI Tool Metadata

This represents information known about applications.

Suggested schema:

| Field                       | Description                                    | Example                     |
| --------------------------- | ---------------------------------------------- | --------------------------- |
| `tool_id`                   | Unique tool identifier                         | `tool_023`                  |
| `tool_name`                 | Application name                               | `Cursor`                    |
| `domain`                    | Primary domain                                 | `cursor.com`                |
| `description`               | Public description of product                  | `AI-powered code editor...` |
| `is_ai_tool`                | Ground-truth label                             | `true`                      |
| `category`                  | AI tool category                               | `Coding Assistant`          |
| `vendor`                    | Vendor/company                                 | `Anysphere`                 |
| `approved_status`           | Synthetic enterprise approval                  | `approved`                  |
| `enterprise_plan_available` | Enterprise controls available                  | `true`                      |
| `sso_available`             | SSO/SAML capability                            | `true`                      |
| `data_retention`            | Simplified policy metadata                     | `30_days`                   |
| `training_on_customer_data` | Whether customer data may be used for training | `false`                     |
| `admin_controls_available`  | Enterprise administration support              | `true`                      |
| `risk_label`                | Optional ground-truth governance label         | `medium`                    |

Some of these fields can come from public datasets or public vendor information.

Others, particularly approval status, should be synthetic.

You do not need perfect real-world vendor security metadata. The purpose is to create enough realistic metadata to test the governance workflow.

---

## Optional Dataset C — Employee Metadata

A separate employee table can make the synthetic environment more realistic.

Example:

| Field           | Example             |
| --------------- | ------------------- |
| `employee_id`   | `emp_0182`          |
| `department`    | `Engineering`       |
| `role`          | `Software Engineer` |
| `location`      | `US`                |
| `business_unit` | `R&D`               |

No real employee information should be used.

---

# 4. Example End-to-End Scenario

Suppose the synthetic activity dataset contains:

`emp_104 | Finance | exampleai.com`

The system has never seen `exampleai.com` before.

The system could:

1. Search the AI-tool metadata dataset.
2. Determine that there is no exact match.
3. Retrieve or inspect available metadata describing the application.
4. Use embeddings/classification/LLM reasoning to determine that it is likely an AI-powered document analysis application.
5. Categorize it as `Document / Productivity AI`.
6. Determine that it is not on the synthetic approved application list.
7. Evaluate available security/governance attributes.
8. Observe that several Finance employees are using it.
9. Produce an assessment such as:

**New unapproved AI tool detected**

Application: ExampleAI

Category: Document AI

Department: Finance

Users: 8

Risk: High

Reasoning: The tool is unapproved, handles uploaded documents, has no identified enterprise administrative controls, and is being used within a potentially sensitive business function.

10. Surface this application in the dashboard for further investigation.

---

# 5. Project Scope

The README.md mentions a number of technologies including classification models, embeddings, clustering, vector databases, RAG, APIs, and dashboards.

Those should be viewed as possible implementation tools rather than separate mandatory deliverables.

The core project should focus on four outcomes:

### 1. Discover AI applications

Determine which applications observed in enterprise activity are AI-related, including applications that may not already exist in a known list.

### 2. Understand what those applications do

Assign meaningful categories and enrich applications with relevant metadata.

### 3. Assess governance concerns

Combine application metadata with enterprise usage context to generate an explainable governance assessment.

### 4. Make the results investigable

Provide a lightweight interface through which a governance analyst can understand AI adoption and investigate applications of interest.

A team that completes these four components will have successfully completed the core project.

---

# 6. What Is Not Required

The following are explicitly not required for the initial version:

* Production-scale data processing
* Integration with real company logs
* Real employee data
* Real-time network monitoring
* A production-grade cybersecurity risk model
* A sophisticated authentication system
* Perfect vendor-security metadata
* A complex frontend
* Training a foundation model
* Building every proposed ML technique

Teams should prefer a smaller end-to-end system that works well over a large collection of disconnected features.

---

# 7. Suggested Technical Blueprint

A possible implementation could look like:

**Synthetic activity data**

↓

**Application/domain extraction**

↓

**Known-tool lookup**

↓

**AI detection model / embedding similarity**

↓

**Tool categorization**

↓

**Metadata enrichment**

↓

**Governance rules + risk reasoning**

↓

**Analytics database**

↓

**Dashboard + investigation interface**

↓

**Optional conversational assistant**

The exact architecture is intentionally open-ended. Part of the project is deciding which techniques are appropriate and comparing different approaches.

---

# 8. Definition of a Successful Final Prototype

By the end of the project, I should be able to give the system a synthetic dataset representing application usage at a fictional enterprise and have the system:

1. Identify the AI applications being used.
2. Detect at least some AI applications that were not explicitly hardcoded.
3. Categorize the applications by purpose.
4. Show which departments or users are using them.
5. Assign an explainable governance/risk assessment.
6. Highlight applications that may deserve investigation.
7. Present the findings through a usable dashboard or interface.
8. Allow an analyst to understand **why** an application was flagged.

The main goal is therefore:

**"Can we turn raw enterprise application activity into useful, explainable AI-governance intelligence?"**
