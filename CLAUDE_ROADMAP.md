# Central Controller Config Tools — Web Application Roadmap

## Project Goals

- Provide web-based utilities for HVAC technicians and installers to work with Mitsubishi Electric controller configuration files
- Eliminate manual data entry by automating `.dat` file generation from `.dsbx` design files
- Drive traffic to main website and online store
- Deploy as Docker container alongside existing web applications
- Reduce friction for non-technical users who cannot install Python dependencies

---

## Overall Architecture

**Suite Name:** Central Controller Config Tools

**Hosting:** Docker container, deployed on existing web server

**Access:** Link from main website home page → Suite hub page → Individual tool pages

**File Limits:** 5 MB maximum for all file uploads

**Session Management:** Auto-delete uploaded files and rearrangements after 1 hour or browser close

---

## Frontend Features

### Suite Hub Page
- **Priority:** High
- **Description:** Landing page for the Central Controller Config Tools suite with links to all four utilities
- **Requirements:**
  - Display name and brief description of each tool
  - Clickable links to navigate to individual tools
  - "How to use" documentation link
  - Visual organization/cards for each tool
- **Technical Notes:** Static page; no backend processing needed beyond serving HTML
- **Dependencies:** None

### "How to Use" Documentation
- **Priority:** High
- **Description:** Page with instructions and guidance for using the tools
- **Requirements:**
  - Step-by-step instructions for each tool
  - Explanation of `.dsbx` and `.dat` file formats (high level)
  - Common troubleshooting/error messages
  - Screenshots or diagrams if helpful
- **Technical Notes:** Static HTML/Markdown content
- **Dependencies:** None

### DSBX to DAT Tool
- **Priority:** High
- **Description:** Convert `.dsbx` design files to `.dat` configuration files with optional group rearrangement
- **Requirements:**
  - Drag-and-drop or file browser upload for `.dsbx` file
  - Two download buttons: "Download for AE-200 Tool" and "Download for AE-C400 Tool"
  - Optional expandable section showing group cards (collapsed by default)
  - Card drag-and-drop interface with fixed group slots (1-50)
  - "Sort by Tag Name" button (if applicable)
  - Error messages for invalid uploads or processing failures
- **Technical Notes:** 
  - Backend parses `.dsbx` to extract all `Groupof50` blocks
  - If multiple blocks detected, generate one `.dat` per block and return as ZIP file
  - If single block, return single `.dat` file
  - Cards show Tag name and M-Net address(es); M-Net addresses stay locked together
  - Only one card per group slot
  - Backend checks for sequential M-Net-to-Group correlation and prompts user to rearrange if detected
  - Backend checks if IC Tag names are in ascending order and prompts user to sort if not
  - Card rearrangements are session-only; lost after 1 hour or browser close
  - Download button triggers backend to apply rearrangements (if any) and generate correct `.dat` for selected tool version
  - Output naming: `{Groupof50_Name}_{tool_version}.dat` (e.g., `Building_A_AE-200.dat`, `Building_B_AE-C400.dat`)
- **Dependencies:** Backend DSBX Parser, Backend DAT Generator, File Upload Handler

### Group Rearranger Tool
- **Priority:** High
- **Description:** Upload existing `.dat` file and rearrange groups before downloading modified `.dat`
- **Requirements:**
  - Drag-and-drop or file browser upload for `.dat` file
  - Expandable section showing group cards (collapsed by default)
  - Card drag-and-drop interface with fixed group slots (1-50)
  - "Sort by Tag Name" button (if applicable)
  - "Download Modified DAT" button
  - Error messages for invalid uploads or processing failures
- **Technical Notes:**
  - Backend parses `.dat` to extract group data
  - Detects if `.dat` contains multiple controllers; if so, return error
  - Cards show Tag name and M-Net address(es); M-Net addresses stay locked together
  - Only one card per group slot
  - Backend checks for sequential M-Net-to-Group correlation and prompts user to rearrange if detected
  - Backend checks if IC Tag names are in ascending order and prompts user to sort if not
  - Card rearrangements are session-only
  - Output `.dat` preserves original ISTool version (AE-200 or AE-C400)
- **Technical Notes:** Reuses card UI component from DSBX to DAT tool
- **Dependencies:** Backend DAT Parser, Backend DAT Regenerator, File Upload Handler

### Generation Change Tool
- **Priority:** High
- **Description:** Convert `.dat` file between AE-200 and AE-C400 ISTool versions (and their paired EW controller types)
- **Requirements:**
  - Drag-and-drop or file browser upload for `.dat` file
  - Auto-detect source ISTool version
  - Single "Download Converted DAT" button (no version selection needed)
  - Error messages for invalid uploads or processing failures
- **Technical Notes:**
  - Four controller types exist across two families: AE-200/EW-50 (AE-200 tool) and AE-C400A/EW-C50 (AE-C400 tool)
  - Backend auto-detects the source family and converts to the opposite: AE-200↔AE-C400A and EW-50↔EW-C50
  - If `.dat` contains multiple controllers, split them and output as ZIP of individual `.dat` files
  - Output files named as: `{controller_name}_AE-200.dat`, `{controller_name}_EW-50.dat`, `{controller_name}_AE-C400A.dat`, or `{controller_name}_EW-C50.dat`
- **Dependencies:** Backend DAT Parser, Backend DAT Converter, File Upload Handler

### Database Decoupler Tool
- **Priority:** High
- **Description:** Split multi-controller `.dat` file into individual database files
- **Requirements:**
  - Drag-and-drop or file browser upload for `.dat` file
  - Single "Download Individual DATs" button
  - Error message if uploaded `.dat` contains only one controller (no split needed)
  - Download as ZIP file containing all output `.dat` files
  - Error messages for invalid uploads or processing failures
- **Technical Notes:**
  - Backend parses `.dat` and extracts all XML entries (1, 1-1, 1-2, 2, etc.)
  - Creates individual `.dat` file for each controller
  - Output naming: `{controller_name}_{controller_type}.dat` (e.g., `Building_A_AE-200.dat`, `Building_B_EW-50.dat`)
  - Package all outputs in ZIP file for download
  - Preserve original ISTool version for each controller
- **Dependencies:** Backend DAT Parser, Backend DAT Splitter, File Upload Handler

---

## Backend Features

### File Upload Handler
- **Priority:** High
- **Description:** Manage file uploads, validation, and temporary storage
- **Requirements:**
  - Accept `.dsbx` and `.dat` file uploads
  - Validate file type (reject if not `.dsbx` or `.dat`)
  - Enforce 5 MB size limit
  - Store uploaded files temporarily with session ID
  - Auto-delete files after 1 hour or session end
  - Return validation errors to frontend with clear messages
- **Technical Notes:**
  - Validate file signatures (ZIP magic bytes) before accepting
  - Store in `/tmp` or equivalent with cleanup via cron/scheduler
  - Generate unique session IDs to isolate user data
- **Dependencies:** None

### DSBX Parser
- **Priority:** High
- **Description:** Extract group configuration data from `.dsbx` (Design Build) files
- **Requirements:**
  - Unzip `.dsbx` file and read internal XML
  - Extract all IndoorUnitGroup data (group numbers, M-Net addresses, Tag names, unit types)
  - Extract SystemRemoteController data (controller model for version detection)
  - Handle both AE-200 and AE-C400 DSB structures
  - Return parsed data as JSON structure matching card layout
  - Handle errors gracefully (corrupt files, missing expected XML paths)
- **Technical Notes:**
  - Reference existing `dsbx_to_dat.py` logic for XML extraction
  - Return group data: `[{group: 1, tag: "Floor-01", mnet_addresses: [50], unit_types: ["IC"]}, ...]`
  - M-Net addresses should be array to handle multi-address groups (IC + RC)
  - Detect and flag groups with sequential M-Net-to-Group correlation (1→1, 2→2, etc.)
  - Detect and flag if IC Tag names are not in ascending order
- **Dependencies:** None

### DAT Parser
- **Priority:** High
- **Description:** Extract group configuration data from `.dat` (encrypted ZIP) files
- **Requirements:**
  - Decrypt `.dat` file using ZipCrypto password "MELCO"
  - Extract and parse internal XML
  - Handle both AE-200 and AE-C400 formats
  - Detect single vs. multi-controller `.dat` files
  - Extract SystemData (controller name, version)
  - Extract ControlGroup data (groups, M-Net addresses, Tag names)
  - Return parsed data in same JSON format as DSBX Parser
  - Handle errors gracefully (corrupt files, wrong password, invalid format)
- **Technical Notes:**
  - Reference existing `convert_dat.py` and `split_dat.py` logic for decryption
  - For multi-controller files, extract each XML entry separately
  - Return group data in same format as DSBX Parser for consistency
  - Detect and flag groups with sequential M-Net-to-Group correlation
  - Detect and flag if IC Tag names are not in ascending order
- **Dependencies:** None

### DAT Generator
- **Priority:** High
- **Description:** Generate valid `.dat` files from parsed group configuration and target ISTool version
- **Requirements:**
  - Accept parsed group configuration (from DSBX Parser or rearranged by user)
  - Accept target version parameter (AE-200 or AE-C400)
  - Generate valid ZipCrypto-encrypted `.dat` file
  - Include all required ZIP entries (main XML, NetworkSetting.xml, IMG/ directory)
  - Use correct XML template for target version
  - Apply group number rearrangements to output XML
  - Return generated `.dat` file as downloadable blob
- **Technical Notes:**
  - Reference existing `dsbx_to_dat.py` for `.dat` generation logic
  - Load appropriate template: `templates/AE-200.xml` or `templates/AE-C400A.xml`
  - Encrypt using password "MELCO"
  - Ensure output is byte-for-byte compatible with ISTool
- **Dependencies:** DAT templates stored in backend

### DAT Converter
- **Priority:** High
- **Description:** Convert `.dat` between AE-200 and AE-C400 versions
- **Requirements:**
  - Accept parsed `.dat` configuration
  - Detect current version; convert to opposite version
  - Preserve all group/M-Net configuration
  - Return converted `.dat` file as downloadable blob
  - Handle multi-controller files by converting each and returning ZIP
- **Technical Notes:**
  - Reference existing `convert_dat.py` logic
  - If input has multiple controllers, use DAT Splitter first, convert each individually, re-package as ZIP
  - Output filenames: `{controller_name}_{new_version}.dat`
- **Dependencies:** DAT Parser, DAT Generator, DAT Splitter

### DAT Splitter
- **Priority:** High
- **Description:** Split multi-controller `.dat` file into individual `.dat` files
- **Requirements:**
  - Accept multi-controller `.dat` file
  - Extract each XML entry (1, 1-1, 1-2, 2, etc.)
  - Create individual `.dat` file for each controller
  - Name output files using SystemData/@Name from each controller
  - Return ZIP file containing all individual `.dat` files
  - Handle single-controller files by returning error message
- **Technical Notes:**
  - Reference existing `split_dat.py` logic
  - Output naming: `{controller_name}_{controller_type}.dat`
  - Detect controller type from XML (AE-200, EW-50, AE-C400A, EW-C50)
  - Preserve original encryption and template structure for each output
- **Dependencies:** DAT Parser, DAT Generator

### DAT Regenerator
- **Priority:** High
- **Description:** Regenerate `.dat` file with rearranged group assignments
- **Requirements:**
  - Accept original `.dat` and rearranged group mapping
  - Parse original `.dat` to extract all configuration
  - Apply new group number assignments to output XML
  - Regenerate `.dat` with same version and settings as original
  - Return regenerated `.dat` file as downloadable blob
- **Technical Notes:**
  - Similar to DAT Generator but preserves all original settings
  - Only group numbers change; M-Net addresses and other data unchanged
  - Preserve original ISTool version (do not convert)
- **Dependencies:** DAT Parser, DAT Generator

### Card Sorting Logic
- **Priority:** Medium
- **Description:** Backend logic for "Sort by Tag Name" functionality
- **Requirements:**
  - Accept parsed group configuration
  - Identify IC units and sort by Tag name (ascending)
  - Identify AIC units; keep separate
  - Identify LC (Lossnay) units; keep separate
  - Reassign group numbers: ICs → groups 1-N, AICs → groups N+1-M, LCs → groups M+1-50
  - Return new group assignment mapping
- **Technical Notes:**
  - Operate on Tag name field only
  - RC units are ignored (they follow their associated IC units)
  - M-Net addresses remain unchanged; only group assignments change
- **Dependencies:** None

### Session Management
- **Priority:** High
- **Description:** Manage user sessions, uploaded files, and rearrangement state
- **Requirements:**
  - Generate unique session ID for each user
  - Store uploaded file path and parsed data per session
  - Store group rearrangement state per session
  - Auto-delete sessions and files after 1 hour
  - Clear sessions on browser close or explicit logout
- **Technical Notes:**
  - Use server-side session storage (Redis, in-memory cache, or database)
  - Implement cleanup job (cron task) to purge expired sessions
  - Session data includes: user's uploaded file, parsed groups, rearrangement state
- **Dependencies:** File Upload Handler

### Error Handling & Validation
- **Priority:** High
- **Description:** Catch and report errors to user with helpful messages
- **Requirements:**
  - Detect and report: invalid file format, corrupt files, wrong file type, file too large
  - Detect and report: DAT files with unsupported controller types
  - Detect and report: DSBX files with missing required data
  - Detect and report: single-controller DAT when multi-controller expected (for Decoupler)
  - Return user-friendly error messages (not stack traces)
  - Log errors server-side for debugging
- **Technical Notes:**
  - Validate at multiple points: file upload, parsing, generation
  - Return HTTP status codes (400 for bad input, 500 for server errors)
  - Include error message in JSON response
- **Dependencies:** All parsing and generation modules

---

## Docker & Deployment

### Docker Container
- **Priority:** High
- **Description:** Package web application and all dependencies as Docker container
- **Requirements:**
  - Create Dockerfile with Python runtime, dependencies (pyzipper, Flask/FastAPI, etc.)
  - Volume mount for temporary file storage (or use container-local `/tmp`)
  - Expose port for web server
  - Include health check
  - Compatible with existing deployment pipeline
- **Technical Notes:**
  - Base image: Python 3.9+ slim
  - Install dependencies: `pip install pyzipper`, web framework, etc.
  - Run web server (Flask/FastAPI) on startup
  - Implement cleanup cron job inside container
- **Dependencies:** None (deployment infrastructure already exists)

---

## Nice-to-Haves (Future)

- Analytics/tracking (view counts, popular tools, error rates) — currently out of scope
- User accounts or authentication — currently out of scope
- Advanced rearrangement features (templates, presets, undo/redo) — consider for Phase 2
- Batch file processing (upload multiple `.dsbx` at once) — consider for Phase 2

---

## Known Constraints

- DSBX to DAT tool handles multiple `Groupof50` blocks in a single `.dsbx` file by generating one `.dat` per block and returning as ZIP
- Multi-controller `.dat` files are split/converted (not modified in place)
- Card rearrangement is session-only; no persistent storage
- File size limit of 5 MB may exclude very large projects (rare in practice)
- No user authentication; assumes trusted usage environment on internal network or public free tool

