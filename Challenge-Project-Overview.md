---

> ## Challenge Advisor: Update & Finalize Your Project Overview
>
> > 💡 **These grey text instructions are just for you, the team's Challenge Advisor; please delete them once you have completed the steps below.**
>
> We've pre-populated this Challenge Project Overview page — which is what will be shared with your Break Through Tech student team in August — using the details from your submission form. You should have received an email inviting you to join this repo as a Collaborator, enabling you to add files and make edits.
> 
> In order for your project to be finalized and assigned to a team, please:
> 1. **Review all sections below** and update or expand any content as needed, making sure to address the SME Feedback in the section immediately below. Look for square brackets to find the places below that require additional inputs from you (e.g., "About [Company / Org Name]").
> 2. **Add your dataset** to the [data folder](data) in this repo.
> 3. **Close the Issue assigned to you in this repo** to let us know that you have made your edits and the overview page is ready for final review. You can do this by going to the _Issues_ tab in the top left section of the menu above, add a comment that says "CA review complete", and click the button to Close the Issue. 
>
> If you're unfamiliar with how to edit a page like this in GitHub, check out [this tutorial](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/handson/edit-readme.html) for a quick overview (start with step 2 and only edit this page), and [this guide](https://ubc-lib-geo.github.io/gis-workshop-waml-template/content/markdown.html) on how to use Markdown to compose text.
>
>
> ❌ Remember that this is a public repo. Do NOT include: Proprietary data, PII, API keys, credentials, or anything confidential.

---

## 📋 BTT Internal Evaluation Notes
*(This section is for BTT staff and CAs only — remove before sharing with students)*

### Technical Vetting
| Check | Status | Notes |
| :--- | :--- | :--- |
| Python Compatibility | 🟢 | The tech stack is primarily centered on Python and leverages well-known libraries for ML and NLP tasks, aligning with the students' ML Foundations experience. |
| Data Readiness | 🟢 | Data is readily available and under 1GB, minimizing potential cleaning overhead. It consists of publicly available datasets and enterprise logs that can be ingested with minimal preprocessing. |
| Resource Check | 🟢 | Using free-tier tools like Google Colab ensures accessibility without relying on specialized hardware or proprietary software. |

### Internal Scores
- **Student Fit Score:** 8/10
- **Technical Depth Score:** 7/10
- **Overall Recommendation:** APPROVE

### Advisor Feedback Draft
This project presents a solid foundation with a clear application in a relevant area of concern for organizations. However, I recommend focusing on integrating disparate datasets for more hands-on learning. Additionally, prioritize a guided approach for the NLP aspect to ensure students engage deeply without becoming overwhelmed. Encourage awareness of a well-structured timeline to keep the team aligned on deliverables.

---

# AI Tool Discovery & Risk Classification

**Company / Org:** Cyera  
**Challenge Advisor:** Shubham Arya, sa2382@cornell.edu  
**Program:** Break Through Tech AI Studio - Fall 2026  

---

## 🏢 About Cyera
Cyera operates in the data security and governance industry, focusing on providing comprehensive visibility and control over an organization's data landscape. Their team aims to help companies address critical challenges related to data security, compliance, and risk management in the modern enterprise.

---

## 🎯 The Challenge
### Project Summary
In this project, you will use enterprise SaaS metadata, browser/network activity logs, employee application usage data, and publicly available AI tool datasets along with NLP, embeddings, clustering, classification models, and LLM-based reasoning techniques to build a system that automatically discovers AI tools used across an organization, classifies their business purpose and risk level, and generates governance insights. This will help our company address the growing challenge of shadow AI adoption, compliance risk, data leakage exposure, and lack of visibility into enterprise AI usage.

### Success Criteria
Success for this project will be measured through a combination of machine learning performance, system usability, and business impact simulation.

Model Performance Metrics   
- Accuracy, precision, recall, and F1 score for identifying whether a tool is AI related
- Multi class classification accuracy for categorizing AI tools into business function categories such as coding assistants, content generation, analytics, or customer support
- Evaluation of risk scoring consistency against predefined governance criteria
- Semantic retrieval relevance for the RAG assistant using similarity scoring and response quality evaluation
- System Functionality Metrics
- Ability to successfully ingest and process synthetic enterprise activity data
- Ability to detect and classify previously unseen AI tools using embeddings and semantic similarity
- Response quality and usefulness of the conversational governance assistant
- Dashboard functionality including filtering, risk visualization, and trend reporting
- User Experience & Business Value

A successful outcome by December would include:   
- A working prototype that provides visibility into enterprise AI tool usage
- Automated identification of potentially high risk or unapproved AI tools
- Actionable governance insights and summaries generated through natural language interaction
- Demonstrated reduction in manual effort required to review and categorize AI tools
- Clear visualizations showing AI adoption trends across departments or business functions

Final Deliverables   

_By the end of the program, the team should deliver:_

- A trained ML classification pipeline
- A governance risk scoring engine
- A RAG based conversational assistant
- A lightweight dashboard or web application
- Technical documentation and a final presentation demonstrating real world applicability of the solution

A highly successful project would demonstrate that the system can accurately classify AI tools, identify governance concerns, and provide meaningful insights that could realistically support enterprise AI governance workflows.


### Project Milestones
Use these milestones to guide your work. Your team will create a GitHub Projects board to track tasks within each milestone.
| Month | Milestone | Key Activities |
|---|---|---|
| September | Problem Definition, Research, and Data Preparation | • Define the business problem around enterprise AI tool visibility and governance<br>• Research existing AI governance and shadow AI management approaches<br>• Identify project scope, user personas, and success metrics<br>• Collect and clean publicly available AI tool datasets and SaaS metadata<br>• Generate synthetic enterprise usage data such as browser logs, application usage records, and department level activity<br>• Perform exploratory data analysis and visualize usage patterns<br>• Define AI tool categories and governance risk criteria<br>• Build initial baseline models for AI tool detection and categorization |
| October | Model Development and Intelligence Layer | • Improve and optimize AI tool classification models using NLP and embeddings<br>• Develop the governance risk scoring engine<br>• Build semantic search and vector retrieval pipeline<br>• Implement a RAG based conversational assistant for governance queries<br>• Test different prompts and evaluate response quality<br>• Develop APIs or backend workflows connecting models and datasets<br>• Begin frontend/dashboard development for displaying governance insights<br>• Conduct intermediate testing and model evaluation |
| November | Integration, Evaluation, and Final Demo | • Integrate all components into a unified application<br>• Finalize dashboard visualizations and conversational assistant experience<br>• Add governance insight summaries and reporting features<br>• Evaluate model accuracy, retrieval quality, and usability<br>• Conduct fairness and bias analysis where applicable<br>• Optimize performance and improve user experience<br>• Prepare final presentation, technical documentation, and live demo<br>• Deliver a working prototype showcasing AI tool discovery, categorization, and governance insights |

> **Note for the team:** Please create a GitHub Projects board in this repository to break these milestones into weekly tasks. Go to the **Projects** tab → **New project** → Choose **Board** → Add columns for each month.

---

## 📊 Dataset
**Name and Source:** [TBD]   
**Format:** CSV/ TSV,JSON,Database export (e.g., SQL dump)   
**Size:** under 1gb   
**Location:** https://www.kaggle.com/datasets/devadigax/aitoolbuzz-com-16k-ai-tools-database

### Key Details
- [Brief description of what's in the data]
- [Any known limitations or preprocessing needed]
- [Link to data dictionary or documentation, if available]

---

## 🛠️ Suggested Approach

**ML Problem Type:** Classification, Clustering, NLP,Deep Learning / Neural Networks, LLMs/ Generative AI, Transfer Learning / Pre-trained Models

**Recommended Libraries:**
- [e.g., pandas, scikit-learn, TensorFlow, Hugging Face]

**Evaluation Metrics:**
- [e.g., Accuracy, Precision/Recall, RMSE, BLEU score]

---

## 📚 Resources to Get Started

The following resources will help your team understand the problem space and potential technical approaches for this project:

**Background Reading:**
- [e.g., Link to an article or blog post about the problem domain]
- [e.g., Link to an industry report or case study]

**Technical Tutorials:**
- [e.g., Link to a free tutorial on the ML technique(s) involved]
- [e.g., Link to documentation for a key library or tool]

**Code Examples:**
- [e.g., Link to a relevant GitHub repo]
- [e.g., Link to a sample implementation or starter code]

**Other:**
- [Links to any additional resources — e.g., papers, videos, podcasts, etc.]

*Feel free to explore beyond these, and share anything interesting you find with me!*

---

## 🤝 How We'll Work Together

**Official check-ins:** During our biweekly 45-minute AI Studio Lab Section meeting block (2nd and 4th week of every month)

 **Other ways to reach out to me with questions:** 
* [e.g., Your team's channel within Break Through Tech’s Discord space]
* [e.g., Email; please copy your teammates and AI Studio Coach]
* [e.g., Request a team check-in on Zoom]
* [Note: I will aim to respond within 48 hours. Please reach out to your AI Studio Coach with urgent questions.]

> 💡 **Challenge Advisor: Please update the above based on your availability and preference. If you are not able to answer questions or meet with fellows outside of the biweekly Lab Section check-ins, simply write in "N/A (only available during the official check-in times)"**

**Recommended free coding / collaboration tools**
* […]
* […]

---

## 🚀 Getting Started

1. **Review this overview document** and note any questions for our first meeting
2. **Begin reviewing the dataset** using the link above
3. **Read the GitHub Projects documentation** [here](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)

I’m excited to work with you!

---

## ❓ Questions?

Please bring any questions to our first meeting during the week of August 24th (Break Through Tech’s Bridge to Studio - Session C). 
