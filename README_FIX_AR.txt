DC Risk Lab - Frontend TypeScript/API status fix

Copy frontend/src/App.tsx from this patch into the same path in your existing project.
This patch:
1. Replaces String.replaceAll calls with compatible replace(/_/g, ' ') calls to remove the TypeScript lib errors shown in VS Code.
2. Makes the initial API health/server check report success correctly and clears a stale API error banner after successful requests.
3. Keeps the thresholds endpoint/fetch logic and all other UI code intact.

Keep your existing backend and data/processed_baselines.json unchanged.
After copying the file:
- Save App.tsx
- Check the VS Code Problems panel
- Restart frontend with `npm run dev` from the frontend folder
- Hard refresh the browser with Ctrl+Shift+R

The backend does not need to be changed for this patch. If TypeScript errors remain, send the new Problems screenshot.
