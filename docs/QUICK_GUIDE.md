# CAM Quick Guide

## Get started

1. Right-click the downloaded CAM zip and choose **Extract All**. Open the new folder. Do not run CAM from inside the zip.
2. Double-click **Start CAM.vbs**. Your browser opens by itself; the first start can take a little longer.
3. Choose where your gradebook will live:
   - Click **Start fresh with sample data** to create it in `Documents\CAM Data`.
   - Or click **Browse...**, choose another local folder, then click **Use this folder**.

![Extract CAM, start it, then choose a separate data folder](quick_guide_images/get-started.svg)

> Keep the CAM app folder and your data folder separate. You can replace the app folder during an update without replacing your gradebook.

## Set up a class

1. In the top bar, click **Add / Edit class** and choose **Add a class**.
2. Enter the class name. Add the grade, MYP year, and subject if you use them.
3. For a local workflow, use **Browse...** beside **Master directory** and select the folder that will hold this class's assignment folders.
4. Click **Create class**.
5. In Window 2, add students one at a time or use the roster import. Check each student's name and email before grading.

![The class setup fields and roster appear before grading](quick_guide_images/set-up-class.svg)

> Criteria A-D are already built in. You choose the criterion when you create an assignment, and every score stays visible in Window 2.

## Add an assignment and enter marks

1. Choose the class and term in the top bar.
2. In Window 1, click **Add assignment / exam**.
3. Enter a name and date, keep **Assignment** selected, choose Criterion A, B, C, or D, then click **Create**.
4. Select a student in Window 2. In Window 3, find the new assignment and enter a mark from 0 to 8. Add a short note if useful.
5. Repeat for the class. CAM saves changes to the gradebook; **Save now** is available for reassurance.

![Create the assignment, choose a student, and enter the criterion mark](quick_guide_images/add-assignment.svg)

> A new assignment shows as missing until you enter a mark or switch that assignment off.

## Grade an exam

1. In Window 1, create a new item and choose **Exam**.
2. Open its analytics, then click **Exam setup**.
3. In the grading workspace, choose the folder of scanned PDFs. Add the question boxes and maximum marks, then click **Process All PDFs**.
4. Grade one question at a time across the class. Use the checklist and comment boxes as you work.
5. Click **Export CSV**. Return to CAM; the marks sync into the exam. Use CAM's exam grading panel to convert the raw total into the criterion grade.

![Scans are sliced into questions, graded, exported, and synced back to CAM](quick_guide_images/grade-exam.svg)

> Scan every paper in the same page order. If CAM warns that one script has a different page count, re-scan it before grading.

## Reports and exports

1. Choose the class and term you want to report.
2. Review the final criterion grades and comments in Window 3.
3. Scroll to **System deliverables**.
4. Click **Build Excel master** for the multi-tab grade workbook, or **Build report-card pack** for one document containing every student's report.
5. When the download button appears, click it and save the file. Select one student first if you only need that student's report.

![Build the class export, then use the download button that appears](quick_guide_images/reports-exports.svg)

> Exports cover the active class only. If files are still waiting in staging, commit them before building reports.

## Back up your term

1. Open **Settings** and find **Term backup and restore**.
2. Beside **Backup folder**, click **Browse...** and choose a folder outside your CAM data folder.
3. Choose the term, then click **Back up term**.
4. Read the success message and confirm the backup file is in the folder you chose.

![Choose an outside backup folder, select the term, and make the snapshot](quick_guide_images/back-up-term.svg)

> Keep a second copy on a USB drive or another safe device. Eject a USB drive properly after the backup finishes. Never delete CAM's existing `.bak-*` files.

## When something goes wrong

### CAM will not start

Double-click **Start CAM (troubleshooting).bat**. Leave the black window open and read the latest message. The same details are saved in `logs\cam.log`. If port 8600 is already in use, close the other CAM window and try again.

### CAM cannot find your gradebook

On the welcome screen, click **Browse...** and choose the folder containing `acm_database.json`. If CAM is already open, use **Settings - Custom Database Path**. Load the existing database when CAM shows its class and student counts; do not choose Replace unless you truly mean to overwrite it.

### You moved to a new laptop

Extract a fresh CAM bundle. Copy or connect your existing data folder, start CAM, and point **Browse...** at that folder. Do not copy `local_device_prefs.json`; each computer keeps its own paths.

![Use the troubleshooting launcher, find the log, or reconnect the existing data folder](quick_guide_images/troubleshooting.svg)
