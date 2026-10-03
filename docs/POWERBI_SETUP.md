# Power BI setup (do this once)

About 20 minutes. You need a Microsoft account that can use Power BI (a university account works).

You will: **A)** create a dataset online, **B)** connect the dashboard file to it, **C)** publish.

---

## A. Create the dataset (online)

1. Go to **app.powerbi.com** and sign in. Open **My workspace**.
2. Press **New item**, choose **Streaming dataset**, then **API**, then **Next**.
3. **Dataset name:** `LegoLiv_Dashboard`
4. Add these **16 values**. Type the names **exactly** (capital letters and underscores matter):

| # | Value name | Type |
|---|---|---|
| 1 | Session | Text |
| 2 | Run_Label | Text |
| 3 | Group_Name | Text |
| 4 | Labor_Cost | Number |
| 5 | Process_Inv | Number |
| 6 | Finished_Inv | Number |
| 7 | Shipped_Cost | Number |
| 8 | Earnings | Number |
| 9 | Total_Cost | Number |
| 10 | Profit | Number |
| 11 | LMPU | Number |
| 12 | Labor_Qty | Number |
| 13 | WIP_Qty | Number |
| 14 | Finished_Qty | Number |
| 15 | Shipped_Qty | Number |
| 16 | Timestamp | DateTime |

5. Switch **Historic data analysis** to **On**. **Leave it On permanently.**
   (This is what keeps every wave stored. Turning it Off deletes all rows.)
6. Press **Create**. Copy the **Push URL** (it starts with `https://api.powerbi.com/`).
   To find it later: My workspace, then `LegoLiv_Dashboard`, then **...**, then **API info**.
7. Keep that URL private. You will paste it into the bot the first time it starts (`START_BOT.bat`).

> The dataset needs at least one row before Power BI Desktop can read its fields. After step 6, start the bot, send one test entry, then continue.

## B. Connect the dashboard file

1. Install **Power BI Desktop** (the installer does this) and sign in with the same account.
2. Open **`dashboard/Legoliv_Dashboard.pbix`**.
3. It was built on another account, so it reports that it cannot load the model. Press **Edit** in that message (or **Home**, **Transform data**, **Data source settings**) and choose **LegoLiv_Dashboard** from **your** workspace.
4. Press **Refresh** on the **Home** ribbon. The fields appear in the Data pane under `RealTimeData`.

The file already contains the **Session dropdown** (styled to match the dashboard), the cards, the chart and the helper measures. If you ever rebuild it from scratch, see **"Rebuilding the session dropdown"** below.

## C. Publish

1. Press **Publish** on the **Home** ribbon and choose **My workspace**.
2. If asked to replace an existing report, press **Replace**.
3. Open **app.powerbi.com**, My workspace, `Legoliv_Dashboard` to view it online.

---

## Rebuilding the session dropdown (only if you start from a blank report)

1. Click an empty spot, then the **Slicer** icon in the Visualizations pane.
2. In the Data pane (`RealTimeData`) tick **Session**.
3. **Format** (paintbrush), **Slicer settings**: Style **Dropdown**, **Single select** On.
4. Create a measure that is 1 only when a session still has entries (this hides removed sessions):

   ```DAX
   Session Has Data =
   IF(
       CALCULATE(COUNTROWS(RealTimeData), RealTimeData[Total_Cost] > 0)
         - CALCULATE(COUNTROWS(RealTimeData), RealTimeData[Total_Cost] < 0) > 0,
       1, 0
   )
   ```

5. With the slicer selected, open the **Filters** pane. Right-click `Session Has Data` in the Data pane, **Add to filters**, **Visual-level filters**. Set **is greater than 0** and press **Apply filter**.
6. The average-efficiency card should use this version so removed (negative) rows do not distort it:

   ```DAX
   LMPU Final =
   DIVIDE(
       DIVIDE(
           SUM(RealTimeData[LMPU]),
           CALCULATE(COUNTROWS(RealTimeData), RealTimeData[Total_Cost] > 0)
             - CALCULATE(COUNTROWS(RealTimeData), RealTimeData[Total_Cost] < 0)
       ), 6)
   ```

## Clearing everything (rarely needed)

In **app.powerbi.com**: My workspace, `LegoLiv_Dashboard` (Semantic model), **...**, **Edit**, scroll to the bottom, switch **Historic data analysis** **Off**, press **Done**. Then open **Edit** again, switch it back **On**, press **Done**. **This permanently deletes every row of every wave.**

After a full wipe, tell the bot to forget its list by sending `/resetledger` in Telegram.
