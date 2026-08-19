/**
 * DMRC INTERN REFERRAL WIZARD — RELEASABLE APPS ENGINE
 * Powered natively by Alpine.js reactive state architecture.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('wizardEngine', () => ({
        // Interface View Layout State
        portalState: 'dashboard', 
        activeTab: 'submitted',
        showValidationWarning: false,
        searchQuery: '',

        // Navigation Controllers
        currentStep: 1,
        highestStepReached: 1,
        totalSteps: 5,
        
        // Identity & Synchronization Stamps
        applicationCode: 'DRAFT · NOT ISSUED',
        saveStatus: 'Not saved yet',
        activeDraftId: null,
        existingTicketId: null, 

        // --- IDENTITY (server-resolved) ---
        // The signed-in DMRC employee. Supplied by the identity layer, which on
        // the intranet reads the payslip login. Referrer fields are filled from
        // here rather than typed, so a referral can never be attributed wrongly.
        identity: null,
        isDevMode: false,
        devEmployeeCode: 'EMP-4471',   // dev only: which employee to impersonate

        dojPicker: null, 

        // Final Submission State
        acceptedDeclarations: false,   
        showSubmitConfirm: false,      
        finalTicket: null,
        // Document rules for every open cycle, keyed by cycle id.
        docRulesByCycle: {},
        capacitiesByCycle: {},
        fallbackCapacities: [],
        // Set only when this portal was opened from the HR dashboard to
        // complete or correct a College Referral.
        institutionalTicket: null,
        institutionalStatus: null,
        institutionalCandidate: '',
        referralCycles: [],
        submittedAt: '',
        reviewSections: { 1: true, 2: false, 3: false, 4: false },

        // WITHDRAWAL STATE
        showWithdrawConfirm: false,
        withdrawAppTarget: null,

        // CORRECTION LOOP STATE
        isCorrectionMode: false, 
        correctionRemarks: '',

        unloadGuard: null,

        // The signed-in referrer. Populated from /api/me/ during init.
        //
        // Deliberately EMPTY rather than carrying a specimen employee. It used
        // to hold a complete, plausible person -- name, designation and
        // department -- so if the identity call ever failed, the form showed a
        // fabricated referrer as though it were real. Blank fields make a
        // failure look like a failure.
        sessionEmployee: {
            empId: '',
            name: '',
            designation: '',
            department: ''
        },

        // Global Application State Matrix
        student: { salutation: '', fullName: '', fathersName: '', gender: '', dateOfBirth: '', mobile_number: '', personal_email: '', permanent_address: '', emergency_contact_name: '', emergency_contact_mobile: '', aadhaar_number: '' },
        academic: { university_name: '', college_name: '', course: '', course_other: '', branch: '', branch_other: '', current_semester: '', grading_system: 'CGPA', current_score: '' },
        // Populated from the configured rules at load, keyed by doc_<doc_type_id>.
        documents: {},
        aadhaarConsent: false,

        // --- DYNAMIC DOCUMENTS ---
        // Whatever the SYS-ADMIN has configured, keyed by doc_<doc_type_id>.
        // Nothing here assumes five documents or any particular name.
        activeDocumentRules: [],
        placement: { cycle_id: null, sessionTerm: '', department_id: '', duration_weeks: '', requested_doj: '', is_ward: false, isInstitutionalMerge: false, referrer_email: '' },

        // --- DATA LISTS (Static Fallbacks) ---
        courseOptions: ['B.Tech / B.E.', 'M.Tech / M.E.', 'BCA', 'MCA', 'B.Sc', 'M.Sc', 'BBA', 'MBA / PGDM', 'B.Com', 'M.Com', 'LLB', 'LLM', 'BA / MA', 'Diploma'],
        branchOptions: ['Computer Science & Engineering', 'Information Technology', 'Electronics & Communication', 'Electrical Engineering', 'Mechanical Engineering', 'Civil Engineering', 'Finance', 'Marketing', 'Human Resources', 'Operations', 'Accounting', 'Commerce', 'Corporate Law', 'General Law', 'Physics', 'Chemistry', 'Mathematics', 'General'],
        stepTitles: { 1: 'Student Details', 2: 'Academic Matrix', 3: 'Document Vault', 4: 'Internship Details' },
        
        // --- DYNAMIC DB INTEGRATIONS (Loaded from TiDB via Django API) ---
        adminCycles: [],
        availableActiveCycles: [],
        activeCycle: null,
        capacities: {},
        dmrcDepartments: [],
        allowedDojDatesByCycle: {},
        adminDocumentRules: [],
        // Derived from the configured rules at load; never hardcoded.
        documentLabels: {},

        get currentCycleCapacity() { return this.capacities; },
        get selectedDeptCapacity() { return this.capacities ? this.capacities[this.placement.department_id] : null; },
        get isWaitlisted() { return !this.placement.is_ward && this.selectedDeptCapacity && (this.selectedDeptCapacity.max - this.selectedDeptCapacity.occ) <= 0; },

        selectedDrawerApp: null,
        applications: [],

        async init() {
            // Which documents the form asks for depends on the cycle. Watching
            // it here covers every route into the wizard -- picking a cycle,
            // resuming a draft, or opening a College Referral -- so no caller
            // has to remember to refresh the list.
            this.$watch('activeCycle', () => this.applyCycleConfiguration());

            const urlParams = new URLSearchParams(window.location.search);

            // --- DEV IDENTITY CARRIED OVER FROM THE HR DASHBOARD ----------
            // Opening this portal in a new tab is a plain browser navigation:
            // it carries no custom header, so in development the request would
            // resolve to this portal's own dev identity -- an ordinary
            // REFERRER, who has no HR dashboard account. The College Referrals
            // endpoint requires one, so the record would come back 403 and the
            // form would open empty.
            //
            // The dashboard therefore passes ?emp=<code>, and it is adopted
            // here BEFORE any request is made, so every call identifies as the
            // HR officer who opened the form.
            //
            // Ignored in production: fetchIdentity() overwrites isDevMode from
            // the server, so once the intranet provider is in place the header
            // stops being sent and identity comes from the login session.
            const empOverride = urlParams.get('emp');
            if (empOverride) {
                this.isDevMode = true;
                this.devEmployeeCode = empOverride;
            }

            await this.fetchIdentity();
            await this.fetchDynamicData();

            // --- COLLEGE REFERRAL HANDOFF ---------------------------------
            // The HR dashboard opens this portal with ?institutional=<ticket>.
            // The record is then read FROM THE SERVER.
            //
            // This replaces a localStorage handoff that carried a COPY of the
            // candidate's data between browser tabs. That copy went stale the
            // moment anything changed, could not survive a refresh, and the
            // dashboard matched the returning candidate by NAME -- which picks
            // the wrong record whenever two candidates share one. The ticket is
            // an identifier; the server holds the data.
            const institutionalTicket = urlParams.get('institutional');
            if (institutionalTicket) {
                await this.loadInstitutionalRecord(institutionalTicket);
                return;   // this portal is now dedicated to that one candidate
            }

            this.fetchReferrerQueue();
        },

        // Every request goes through this so the identity header is never
        // forgotten. Ignored by the server in production, where identity comes
        // from the intranet session instead.
        authHeaders(extra = {}) {
            const headers = { ...extra };
            if (this.isDevMode && this.devEmployeeCode) {
                headers['X-DMRC-Employee'] = this.devEmployeeCode;
            }
            return headers;
        },

        async fetchServerDrafts() {
            try {
                const res = await fetch('http://127.0.0.1:8000/api/drafts/', { headers: this.authHeaders() });
                if (!res.ok) { console.error('Draft fetch failed:', res.status); return []; }
                return await res.json();
            } catch (err) {
                console.error('Draft fetch failed:', err);
                return [];
            }
        },

        // Autosave. Debounced by the caller; safe to invoke on every step change.
        async saveServerDraft() {
            if (this.finalTicket) return;                  // already submitted
            if (this.highestStepReached <= 1 && !this.activeDraftId) return;
            try {
                const res = await fetch('http://127.0.0.1:8000/api/drafts/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        id: this.activeDraftId,
                        cycleId: this.placement.cycle_id || (this.activeCycle ? this.activeCycle.id : null),
                        currentStep: this.currentStep,
                        highestStep: this.highestStepReached,
                        payload: {
                            student: this.student,
                            academic: this.academic,
                            placement: this.placement
                            // documents are NOT sent here: they are owned by the
                            // draft-document endpoint and merged server-side, so
                            // an autosave can never wipe an uploaded file.
                        }
                    })
                });
                if (res.status === 404 && this.activeDraftId) {
                    // The draft no longer exists (purged, or an id from an older
                    // session). Forget it and create a new one instead of
                    // failing every save from here on.
                    console.warn('Draft', this.activeDraftId, 'no longer exists; creating a new one.');
                    this.activeDraftId = null;
                    return await this.saveServerDraft();
                }
                if (!res.ok) { console.error('Draft save failed:', await res.text()); return; }
                const saved = await res.json();
                this.activeDraftId = saved.id;
                this.saveStatus = new Date().toLocaleTimeString();
            } catch (err) {
                console.error('Draft save failed:', err);
            }
        },

        async discardServerDraft(draftId) {
            try {
                await fetch(`http://127.0.0.1:8000/api/drafts/?id=${draftId}`, {
                    method: 'DELETE', headers: this.authHeaders()
                });
            } catch (err) { console.error('Draft discard failed:', err); }
        },

        // Uploads a document straight onto the draft so it survives to any other
        // machine. Replacing a file is a true overwrite -- a draft is not an
        // audit record, so there is no previous version to preserve.
        async uploadDraftDocument(docKey, file) {
            if (!this.activeDraftId) await this.saveServerDraft();
            if (!this.activeDraftId) { console.error('No draft to attach document to.'); return null; }
            const form = new FormData();
            form.append('draft_id', this.activeDraftId);
            form.append('doc_key', docKey);
            form.append('file', file);
            try {
                const res = await fetch('http://127.0.0.1:8000/api/drafts/document/', {
                    method: 'POST', headers: this.authHeaders(), body: form
                });
                if (!res.ok) {
                    alert('Upload failed: ' + await res.text());
                    return null;
                }
                return await res.json();
            } catch (err) {
                console.error('Draft document upload failed:', err);
                alert('Upload failed: could not reach the server.');
                return null;
            }
        },

        async fetchIdentity() {
            try {
                const res = await fetch('http://127.0.0.1:8000/api/me/', { headers: this.authHeaders() });
                if (!res.ok) { console.error('Identity check failed:', res.status); return false; }
                const me = await res.json();
                this.identity = me;
                this.isDevMode = !!me.devMode;

                // The degree and branch lists come from the SERVER, so this
                // form and the College Referrals intake can never offer
                // different options for the same field. The arrays below stay
                // as a fallback for the moment before this call returns.
                if (me.academicOptions) {
                    if (Array.isArray(me.academicOptions.courses) && me.academicOptions.courses.length)
                        this.courseOptions = me.academicOptions.courses;
                    if (Array.isArray(me.academicOptions.branches) && me.academicOptions.branches.length)
                        this.branchOptions = me.academicOptions.branches;
                }
                // Referrer block is now authoritative, not a hardcoded mock.
                this.sessionEmployee = {
                    empId: me.employeeCode,
                    name: me.fullName,
                    designation: me.designation || '',
                    department: me.department || ''
                };
                return true;
            } catch (err) {
                console.error('Identity check failed:', err);
                return false;
            }
        },

        async fetchDynamicData() {
            try {
                // Single employee-level endpoint. The admin endpoints this used
                // to call are SYS-ADMIN only -- a real referrer would get 403.
                const bootstrapRes = await fetch('http://127.0.0.1:8000/api/portal/bootstrap/', {
                    headers: this.authHeaders()
                });
                const cycleRes = bootstrapRes;
                const configRes = bootstrapRes;
                const bootstrapData = bootstrapRes.ok ? await bootstrapRes.json() : null;

                if (cycleRes.ok) {
                    const cycleData = bootstrapData;
                    this.adminCycles = cycleData.cycles;
                    
                    this.availableActiveCycles = this.adminCycles.filter(c => c.isActive);
                    if (this.availableActiveCycles.length > 0) {
                        this.activeCycle = this.availableActiveCycles[0];
                    }
                    
                    // Capacities PER CYCLE. Each cycle sets its own quotas and
                    // has its own occupancy, so both the department list and the
                    // seats-remaining figures depend on which cycle is selected.
                    this.capacitiesByCycle = cycleData.capacitiesByCycle || {};
                    this.fallbackCapacities = cycleData.capacities || [];
                    this.allowedDojDatesByCycle = cycleData.allowedDojDatesByCycle || {};
                }

                if (configRes.ok) {
                    const configData = bootstrapData;
                    this.adminDocumentRules = configData.docRules || [];
                    // Document rules PER CYCLE. DMRC runs concurrent cycles and
                    // each configures its own document set, so which documents
                    // this form asks for depends on the cycle being applied to.
                    this.docRulesByCycle = configData.docRulesByCycle || {};
                    this.applyCycleConfiguration();
                    
                    // Labels are built from rule.key above. The previous version
                    // matched rule names with .includes('AADHAR') etc, which
                    // silently broke if a document was renamed and could never
                    // accommodate a sixth document.
                }
            } catch (err) {
                console.error("Failed to fetch dynamic data from database:", err);
            }
        },

        async fetchReferrerQueue() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/apply/', { headers: this.authHeaders() });
                if (response.ok) {
                    let liveApps = await response.json();
                    // Drafts are server-side now, so they follow the referrer to
                    // any machine they sign in from. localStorage is no longer used.
                    let localDrafts = await this.fetchServerDrafts();
                    this.applications = [...liveApps, ...localDrafts];
                } else {
                    console.error("Failed to load Referrer Queue from Django.");
                    this.applications = [];
                }
            } catch (error) {
                console.error("Network error fetching Referrer Queue:", error);
                this.applications = [];
            }
        },

        getDisplayDojLabel(status) { return ['Scheduled', 'Pending Joining', 'Fix Joining', 'Offer Ready'].includes(String(status)) ? 'Allotted DOJ' : (['Joined', 'Active Intern', 'Fix Clearance', 'Pending Clearance', 'Pending Dispatch', 'Completed'].includes(String(status)) ? 'Actual DOJ' : 'Requested DOJ'); },
        getDisplayDojValue(app) { if (!app) return ''; const status = app.dbStatus || app.status; if (['Scheduled', 'Pending Joining', 'Fix Joining', 'Offer Ready'].includes(status)) return app.allottedDoj || app.doj; if (['Joined', 'Active Intern', 'Fix Clearance', 'Pending Clearance', 'Pending Dispatch', 'Completed'].includes(status)) return app.actualDoj || app.allottedDoj || app.doj; return app.doj; },

        get sortedAndFilteredApps() {
            let filtered = this.applications.filter(app => {
                if (!this.searchQuery) return true;
                const query = this.searchQuery.toLowerCase();
                return app.student?.fullName?.toLowerCase().includes(query) || app.ticketId?.toLowerCase().includes(query);
            });
            return filtered.sort((a, b) => b.createdDate.split('-').reverse().join('-').localeCompare(a.createdDate.split('-').reverse().join('-'))); 
        },

        // True when a configured document requires explicit consent (Aadhaar).
        // Drives the consent checkbox AND the Aadhaar number field, so disabling
        // the document removes all three together.
        // The key of the document requiring consent, or null if none is active.
        // Point the form at the selected cycle's configuration: its documents,
        // its departments and its seat counts.
        //
        // Rules ARE the document list: slots, labels, formats, mandatory flags,
        // the consent checkbox and the identity-number field all derive from
        // it, so a document disabled for this cycle takes all of its fields
        // with it and no special-casing is needed anywhere.
        //
        // Called whenever the selected cycle changes. Previously the form used
        // one list merged across every active cycle, so a document another
        // cycle still required went on being demanded here.
        applyCycleConfiguration() {
            const key = this.activeCycle ? String(this.activeCycle.id) : null;

            // --- DEPARTMENTS AND SEATS ---------------------------------
            // Previously built from a list flattened across every active cycle,
            // which listed each department once per cycle -- Civil twice, IT
            // twice -- and let the later cycle's quota and occupancy overwrite
            // the earlier one's, so the availability shown belonged to the
            // wrong cycle entirely.
            const caps = (key && this.capacitiesByCycle && this.capacitiesByCycle[key])
                         ? this.capacitiesByCycle[key]
                         : (this.fallbackCapacities || []);
            const capObj = {};
            const depts = [];
            caps.forEach(c => {
                capObj[c.dept] = { max: c.quota, occ: c.occupied };
                if (!depts.includes(c.dept)) depts.push(c.dept);
            });
            this.capacities = capObj;
            this.dmrcDepartments = depts;

            // A department this cycle does not offer cannot stay selected.
            if (this.placement.department_id && !depts.includes(this.placement.department_id)) {
                this.placement.department_id = '';
            }

            // --- DOCUMENTS ---------------------------------------------
            const rules = (key && this.docRulesByCycle && this.docRulesByCycle[key])
                          ? this.docRulesByCycle[key]
                          : (this.adminDocumentRules || []);

            this.activeDocumentRules = rules;
            this.documentLabels = {};
            rules.forEach(rule => {
                this.documentLabels[rule.key] = rule.name;
                if (!(rule.key in this.documents)) this.documents[rule.key] = null;
            });

            // Drop anything uploaded against a document this cycle does not ask
            // for, so it cannot be counted towards completion or submitted.
            const liveKeys = rules.map(r => r.key);
            Object.keys(this.documents).forEach(k => {
                if (!liveKeys.includes(k)) delete this.documents[k];
            });

            // The consent tick belongs to a document. If that document is no
            // longer part of this cycle, a tick left set would be consent to
            // something the candidate was never asked for.
            if (!this.consentDocumentKey) this.aadhaarConsent = false;
        },

        get consentDocumentKey() {
            const rule = this.activeDocumentRules.find(r => r.requiresConsent);
            return rule ? rule.key : null;
        },

        get requiresIdentityNumber() {
            return this.activeDocumentRules.some(r => r.requiresConsent);
        },

        get savedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'saved'); },
        get submittedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'submitted'); },
        get reopenedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'reopened'); },

        // --- CYCLE DATE LOGIC HELPERS ---
        getTodayString() {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        },

        isWithinWindow(cycle) {
            if (!cycle || !cycle.start || !cycle.end) return false;
            const todayStr = this.getTodayString();
            return todayStr >= cycle.start && todayStr <= cycle.end;
        },

        getCycleStatusMessage(cycle) {
            if (!cycle || !cycle.start || !cycle.end) return '';
            const todayStr = this.getTodayString();
            if (todayStr < cycle.start) return `Registration opens on ${this.displayDate(cycle.start)}.`;
            if (todayStr > cycle.end) return `Registration closed on ${this.displayDate(cycle.end)}.`;
            return 'Registration is currently open.';
        },
        // --------------------------------

        viewTicket(app) { this.selectedDrawerApp = app; new bootstrap.Offcanvas(document.getElementById('ticketDrawer')).show(); },

        startNewApplication() {
            this.resetFormState();
            // Draft ids are issued by the SERVER now. Fabricating one here (the
            // old localStorage design used Date.now()) makes every save target a
            // draft that does not exist, and the API correctly refuses with
            // "Draft not found." Left null: the first autosave creates the row
            // and stores the real id returned by the server.
            this.activeDraftId = null;
            this.portalState = 'cycle_select';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        beginWizard() {
            if (!this.activeCycle) return;

            // A COLLEGE REFERRAL is already a filed application: it has a real
            // ticket, and its cycle was fixed at intake. So the cycle is not
            // re-chosen here, the ticket is not replaced with a PENDING
            // placeholder, and a closed application window does NOT block the
            // form -- a closed cycle stops NEW intakes, it must never strand a
            // candidate already in the pipeline.
            if (this.placement.isInstitutionalMerge) {
                this.initializeWizard();
                return;
            }

            if (!this.isWithinWindow(this.activeCycle)) return;
            let parts = this.activeCycle.name.split(' ');
            this.placement.sessionTerm = parts[0];
            let year = parts[1] || new Date().getFullYear();
            this.placement.cycle_id = this.activeCycle.id;
            this.applicationCode = `DMRC-${year}${this.placement.sessionTerm.substring(0,1).toUpperCase()}-PENDING`;
            this.initializeWizard();
        },

        returnToDashboard() {
            if (this.unloadGuard) { window.removeEventListener('beforeunload', this.unloadGuard); this.unloadGuard = null; }
            if (this.placement.isInstitutionalMerge) { window.close(); window.location.href = '../Phase-2-HR-Dashboard/hr_dashboard.html'; return; }

            this.autoSaveWip();

            this.resetFormState();
            this.portalState = 'dashboard';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        // Whether a saved draft can still be opened, and why not if it cannot.
        // A draft outlives nothing: its cycle may have closed or been archived
        // since it was saved.
        draftBlockReason(app) {
            const cycleId = app.cycle_id || (app.placement ? app.placement.cycle_id : null);
            const cycle = this.availableActiveCycles.find(c => c.id === cycleId);
            if (!cycle) {
                return `${app.targetCycle || 'That cycle'} has been closed and archived. `
                     + `This draft can no longer be opened or submitted.`;
            }
            if (!this.isWithinWindow(cycle)) {
                return this.getCycleStatusMessage(cycle)
                     + ' Saved drafts can only be submitted while the cycle is open.';
            }
            return '';
        },

        canResumeDraft(app) { return this.draftBlockReason(app) === ''; },

        resumeDraft(app) {
            // The SAME window rule as starting a new application. Resuming used
            // to have no check at all, so a draft saved before the closing date
            // could be completed and submitted afterwards.
            const blocked = this.draftBlockReason(app);
            if (blocked) { alert(blocked); return; }

            this.resetFormState();
            this.activeDraftId = app.id; 
            
            let term = app.sessionTerm || (app.placement ? app.placement.sessionTerm : 'Winter');
            let cycleName = app.targetCycle || (term + ' ' + new Date().getFullYear()); 
            let year = cycleName.split(' ')[1] || new Date().getFullYear();
            this.applicationCode = `DMRC-${year}${term.substring(0,1).toUpperCase()}-PENDING`;
            
            this.placement.cycle_id = app.cycle_id || (app.placement ? app.placement.cycle_id : null);
            this.placement.sessionTerm = term;

            // NO FALLBACK to the first available cycle. That silently turned a
            // draft whose cycle had gone into an application for a DIFFERENT
            // cycle -- carrying that cycle's document rules and joining dates,
            // with nothing on screen to say so. draftBlockReason above has
            // already refused this case, so the cycle is known to exist.
            this.activeCycle = this.availableActiveCycles.find(c => c.id === this.placement.cycle_id);
            
            this.initializeWizard(); 
            
            setTimeout(() => {
                this.loadMockDataIntoForm(app);
                // Restore documents already uploaded against this draft so the
                // referrer sees their files rather than empty slots.
                if (app.documents && typeof app.documents === 'object') {
                    // A document disabled since this draft was saved is discarded:
                    // it is no longer part of the workflow, so carrying it forward
                    // would submit something nobody asked for.
                    const liveKeys = this.activeDocumentRules.map(r => r.key);
                    Object.entries(app.documents).forEach(([key, entry]) => {
                        if (!liveKeys.includes(key)) return;
                        if (entry && entry.path) {
                            this.documents[key] = {
                                file: null,
                                name: entry.name,
                                path: entry.path,
                                previewUrl: 'http://127.0.0.1:8000' + (entry.url || '')
                            };
                        }
                    });
                }
                // Only a genuine DRAFT carries a draft id. A reopened application
                // has an APPLICATION id, and assigning it here made every autosave
                // target a draft that does not exist -- the 404 recovery then
                // created a fresh one, leaving a duplicate in Saved Drafts.
                this.activeDraftId = (app.tab === 'saved' && app.id) ? app.id : null;
                // Do NOT clear isCorrectionMode here. fixApplication() calls
                // resumeDraft() and then sets the correction flags immediately;
                // this deferred callback used to run 50ms later and silently
                // reset the flag, so the ticket_id was never attached and the
                // resubmission was saved as a brand-new application.
                // The flag is cleared by resetFormState() instead.
                this.highestStepReached = app.highestStepReached || 1; 
                this.currentStep = app.currentStep || 1;
            }, 50);
        },

        fixApplication(app) { 
            this.resumeDraft(app); 
            // resumeDraft() defers part of its work by 50ms, so the correction
            // state is applied afterwards to guarantee it wins. existingTicketId
            // is what tells the backend to UPDATE this application rather than
            // create a new one -- if it is missing, the resubmission silently
            // becomes a fresh application with a new ticket number.
            this.isCorrectionMode = true; 
            // actionRequired is the server's instruction for THIS bounce:
            // "Choose a new Date of Joining." for a no-show, or
            // "Correction Requested: <HR's remark>" for a document correction.
            this.correctionRemarks = app.actionRequired || app.rejectionRemarks || app.remarks || 'Correction requested by HR.'; 
            this.existingTicketId = app.ticketId; 
            setTimeout(() => {
                this.isCorrectionMode = true;
                this.existingTicketId = app.ticketId;
                this.highestStepReached = 5;
                if (!this.existingTicketId) {
                    console.error('fixApplication: no ticketId on', app,
                                  '-- resubmission would be saved as a new application.');
                }
            }, 60);
        },

        canWithdraw(app) { return app && !['Joined', 'Active Intern', 'Fix Clearance', 'Pending Clearance', 'Pending Certificate', 'Pending Dispatch', 'Completed', 'Rejected', 'Draft'].includes(app.dbStatus || app.status) && app.tab !== 'saved'; },
        confirmWithdraw(app) { this.withdrawAppTarget = app; this.showWithdrawConfirm = true; },
        async executeWithdraw() {
            if (!this.withdrawAppTarget) return;
            let app = this.withdrawAppTarget;

            try {
                const response = await fetch('http://127.0.0.1:8000/api/apply/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: app.ticketId, action: 'withdraw' })
                });

                if (!response.ok) throw new Error("Backend synchronization failed.");

                if (!app.isWard && app.dept && app.dept !== '—' && this.capacities[app.dept]?.occ > 0) {
                    this.capacities[app.dept].occ--;
                }
                
                app.status = 'Rejected'; 
                app.dbStatus = 'Rejected'; 
                app.badge = 'bg-danger'; 
                app.remarks = 'Withdrawn by Referrer.'; 
                app.rejectionCategory = 'Withdrawn';
                
                if (app.tab === 'reopened') app.tab = 'submitted';
                if (!app.timeline) app.timeline = [];
                
                const now = new Date();
                const timeString = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
                const dateString = now.toLocaleDateString('en-GB').replace(/\//g, '-');
                
                app.timeline.push({ 
                    date: `${dateString} ${timeString}`, 
                    title: 'Status: Rejected', 
                    desc: 'Withdrawn by Referrer.' 
                });
                
                this.showWithdrawConfirm = false; 
                this.withdrawAppTarget = null;
                const offcanvasElement = document.getElementById('ticketDrawer'); 
                if (offcanvasElement) bootstrap.Offcanvas.getInstance(offcanvasElement)?.hide();

            } catch (error) {
                console.error("Withdrawal Error:", error);
                alert("Network Error: Could not withdraw application. Please check your connection to the DMRC Intranet and try again.");
                this.showWithdrawConfirm = false;
            }
        },

        // Autosave to the server. Was localStorage, which meant a draft was
        // trapped in one browser -- the opposite of what the draft stage exists
        // for. Files are handled separately by uploadDraftDocument().
        autoSaveWip() {
            const dobInput = document.querySelector('input[x-model="student.dateOfBirth"]');
            if (dobInput && dobInput.value) this.student.dateOfBirth = dobInput.value;

            if (this.placement.isInstitutionalMerge) return;   // handled by the HR merge flow

            if (this.highestStepReached > 1 && !this.finalTicket) {
                // Debounced: the wizard fires this on every step change and the
                // autosave is a network call now, not a synchronous write.
                clearTimeout(this._draftSaveTimer);
                this._draftSaveTimer = setTimeout(() => this.saveServerDraft(), 400);
            }
        },

        // Pull one College Referral record and open the wizard on it.
        //
        // Everything the college supplied is prefilled and REMAINS EDITABLE:
        // a detail taken down wrongly from an institution's list should be
        // fixable here rather than sending HR back to the dashboard.
        async loadInstitutionalRecord(ticket) {
            this.resetFormState();

            let record = null;
            let failure = null;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/college-referrals/', {
                    headers: this.authHeaders()
                });
                if (response.ok) {
                    const data = await response.json();
                    record = (data.records || []).find(r => r.ticket === ticket) || null;
                    if (record) this.referralCycles = data.cycles || [];
                    if (!record) failure = 'not-found';
                } else if (response.status === 401 || response.status === 403) {
                    // Distinguished deliberately: "you are not permitted to read
                    // this" and "this record is gone" have different causes and
                    // different fixes, and reporting the first as the second
                    // sends HR looking for a record that is sitting there.
                    failure = 'forbidden';
                } else {
                    failure = 'server';
                }
            } catch (err) {
                console.error('Could not load the institutional record:', err);
                failure = 'network';
            }

            if (!record) {
                if (failure === 'forbidden') {
                    alert(`You are not signed in with an HR account, so ${ticket} could not be opened.\n\n`
                          + `Open this form from the College Referrals section of the HR `
                          + `dashboard rather than from a saved or copied link.`);
                } else if (failure === 'network' || failure === 'server') {
                    alert(`${ticket} could not be loaded because the server could not be reached.\n\n`
                          + `Check that the Django server is running, then try again.`);
                } else {
                    alert(`Application ${ticket} could not be found.\n\n`
                          + `It may already have been merged or rejected. Return to the `
                          + `HR dashboard and reopen it from the College Referrals section.`);
                }
                return;
            }

            this.institutionalTicket = ticket;
            this.institutionalStatus = record.status;
            this.institutionalCandidate = record.name || '';
            // Submitting sends this back as ticket_id, so the server updates the
            // existing record rather than creating a second application.
            this.existingTicketId = ticket;
            this.applicationCode = ticket;

            // Resolve the cycle BY ID, from the record itself. Matching on the
            // displayed label was fragile: any mismatch left the cycle unset,
            // and the wizard then refused to open and dropped the user on the
            // referrer's dashboard with no explanation -- which is exactly what
            // it did.
            // By ID first, from either list. Falling back to the displayed
            // label last: matching on a label is what failed before, but as a
            // final resort it is better than refusing to open a record whose
            // cycle plainly exists.
            const byId = c => record.cycleId != null && c.id === record.cycleId;
            const byName = c => record.cycle && c.name === record.cycle;
            this.activeCycle =
                   this.referralCycles.find(byId)
                || this.adminCycles.find(byId)
                || this.referralCycles.find(byName)
                || this.adminCycles.find(byName)
                || null;

            if (!this.activeCycle) {
                alert(`${ticket} could not be opened because its internship cycle `
                      + `could not be identified.\n\nCheck that the cycle still exists `
                      + `in the Admin Control Center, then try again.`);
                return;
            }

            this.placement.cycle_id = this.activeCycle.id;
            this.placement.sessionTerm = this.activeCycle.term
                                         || (record.cycle ? record.cycle.split(' ')[0] : '');

            // --- what the college sent, plus anything already recorded ---
            const bio = record.bio || {};
            const acad = record.academic || {};

            this.student.fullName = record.name || '';
            this.student.personal_email = bio.email || '';
            this.student.mobile_number = bio.mobile || '';
            this.student.salutation = bio.salutation || '';
            this.student.fathersName = bio.father || '';
            this.student.gender = bio.gender || '';
            this.student.dateOfBirth = bio.dob || '';
            this.student.aadhaar_number = bio.aadhaar_number || '';
            this.student.permanent_address = bio.address || '';
            this.student.emergency_contact_name = bio.emergencyName || '';
            this.student.emergency_contact_mobile = bio.emergencyMobile || '';

            this.academic.university_name = acad.university || '';
            this.academic.college_name = acad.college || '';
            const restoredCourse = this.applyOption(acad.course, this.courseOptions);
            this.academic.course = restoredCourse.selected;
            this.academic.course_other = restoredCourse.other;
            const restoredBranch = this.applyOption(acad.branch, this.branchOptions);
            this.academic.branch = restoredBranch.selected;
            this.academic.branch_other = restoredBranch.other;
            this.academic.current_semester = acad.semester || '';
            this.academic.grading_system = acad.grading || 'CGPA';
            this.academic.current_score = acad.score || '';

            this.placement.department_id = record.department || '';
            this.placement.duration_weeks = record.internship && record.internship.duration
                ? String(record.internship.duration).split(' ')[0] : '';
            // The date HR allotted at scheduling. Editable here -- if a different
            // one is chosen, that later decision replaces it.
            this.placement.requested_doj = record.allottedDoj || '';
            this.placement.isInstitutionalMerge = true;
            this.placement.is_ward = false;          // never applies to a college referral
            this.placement.referrer_email = '';      // there is no employee referrer

            // Documents already collected show as present, so reopening the form
            // to fix one field does not demand re-uploading everything. Only
            // files actually re-chosen are sent, and only those are superseded.
            if (record.docs) {
                Object.keys(record.docs).forEach(key => {
                    const doc = record.docs[key];
                    if (doc && doc.name) {
                        this.documents[key] = { name: doc.name, previewUrl: doc.viewUrl || null };
                    }
                });
            }

            // A record already complete is being CORRECTED, so every step is
            // reachable at once rather than making HR walk the wizard again.
            const isCorrection = record.status === 'Ready for Merge';
            this.currentStep = 1;
            this.highestStepReached = isCorrection ? this.totalSteps : 1;

            // Open on the cycle screen, not the referrer's dashboard. That
            // dashboard is a referrer's own list of their referrals -- it has
            // nothing to do with this candidate and only gets in the way. This
            // is the start of the application flow, and it confirms which cycle
            // and candidate is about to be filled in.
            this.portalState = 'cycle_select';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        loadMockDataIntoForm(app) {
            if (app.student) Object.assign(this.student, JSON.parse(JSON.stringify(app.student))); 
            if (app.academic) Object.assign(this.academic, JSON.parse(JSON.stringify(app.academic))); 
            
            if (app.placement && Object.keys(app.placement).length > 0) {
                Object.assign(this.placement, JSON.parse(JSON.stringify(app.placement)));
            } else {
                this.placement.department_id = app.dept !== '—' ? app.dept : ''; this.placement.duration_weeks = app.duration ? app.duration.charAt(0) : ''; this.placement.requested_doj = app.doj || ''; this.placement.is_ward = app.isWard || false; this.placement.referrer_email = app.referrer_email || ''; this.placement.cycle_id = app.cycle_id || null; this.placement.sessionTerm = app.sessionTerm || '';
            }

            if (app.documents) {
                for(let key in app.documents) {
                    if (app.documents[key]) {
                        if (app.documents[key].file instanceof File) {
                            this.documents[key] = app.documents[key]; 
                        } else if (!app.documents[key].hasOwnProperty('file') && app.documents[key].name) {
                            this.documents[key] = { name: app.documents[key].name, previewUrl: app.documents[key].previewUrl || `./Dummy Docs/${app.documents[key].name}` };
                        } else {
                            this.documents[key] = null;
                        }
                    } else {
                        this.documents[key] = null;
                    }
                }
                if (this.consentDocumentKey && this.documents[this.consentDocumentKey]) this.aadhaarConsent = true;
            }

            setTimeout(() => {
                const dobInput = document.querySelector('input[x-model="student.dateOfBirth"]');
                if (dobInput && dobInput._flatpickr) dobInput._flatpickr.setDate(this.student.dateOfBirth);
                
                if (this.dojPicker) {
                    if(this.activeCycle && this.allowedDojDatesByCycle[this.activeCycle.name]) {
                        this.dojPicker.set('enable', this.allowedDojDatesByCycle[this.activeCycle.name]);
                    }
                    this.dojPicker.setDate(this.placement.requested_doj);
                }
            }, 100);
        },

        resetFormState() {
            Object.assign(this.student, { salutation: '', fullName: '', fathersName: '', gender: '', dateOfBirth: '', mobile_number: '', personal_email: '', permanent_address: '', emergency_contact_name: '', emergency_contact_mobile: '', aadhaar_number: '' });
            Object.assign(this.academic, { university_name: '', college_name: '', course: '', course_other: '', branch: '', branch_other: '', current_semester: '', grading_system: 'CGPA', current_score: '' });
            Object.assign(this.placement, { cycle_id: null, sessionTerm: '', department_id: '', duration_weeks: '', requested_doj: '', is_ward: false, isInstitutionalMerge: false, referrer_email: '' });
            
            this.documents = { aadhar: null, college_id: null, lor: null, photograph: null, signature: null };
            this.aadhaarConsent = false; this.acceptedDeclarations = false; this.isCorrectionMode = false; this.correctionRemarks = ''; this.currentStep = 1; this.highestStepReached = 1; this.finalTicket = null; this.activeDraftId = null; this.existingTicketId = null;
        },

        initDOJCalendar(element) { 
            let allowedDates = [];
            if (this.activeCycle && this.allowedDojDatesByCycle[this.activeCycle.name]) {
                allowedDates = this.allowedDojDatesByCycle[this.activeCycle.name];
            }

            const options = {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd-m-Y',
                minDate: "today",
                defaultDate: this.placement.requested_doj || null,
                onChange: (selectedDates, dateStr) => {
                    this.placement.requested_doj = dateStr;
                }
            };

            if (this.placement.isInstitutionalMerge) {
                // COLLEGE REFERRALS: every date is selectable, with the cycle's
                // approved dates highlighted.
                //
                // An employee referrer may only REQUEST one of the published
                // dates -- that restriction is what keeps the intake orderly.
                // Here DMRC has already committed to a date with the
                // institution, and a candidate who missed their slot or was
                // agreed a different one must still be recordable. Restricting
                // the picker would leave HR unable to enter the true date.
                //
                // The highlight comes from the same cycle configuration, so a
                // SYS-ADMIN's changes are reflected here immediately.
                options.onDayCreate = (dObj, dStr, fp, dayElem) => {
                    const y = dayElem.dateObj.getFullYear();
                    const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                    const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                    if (allowedDates.includes(`${y}-${m}-${d}`)) dayElem.classList.add('doj-approved-date');
                };
            } else {
                // Employee referrals stay restricted to the published calendar.
                options.enable = allowedDates;
            }

            this.dojPicker = flatpickr(element, options);
        },

        restrictMobileInput(fieldPath, nextFieldId) { let clean = this.student[fieldPath].replace(/\D/g, '').substring(0, 10); this.student[fieldPath] = clean; if (clean.length === 10 && nextFieldId) this.$nextTick(() => document.getElementById(nextFieldId)?.focus()); },
        restrictAadhaarInput() { this.student.aadhaar_number = this.student.aadhaar_number.replace(/\D/g, '').substring(0, 12); },
        isMobileInvalid(fieldPath) { return this.student[fieldPath].length > 0 && this.student[fieldPath].length < 10; },
        isAadhaarInvalid() { return this.student.aadhaar_number.length > 0 && this.student.aadhaar_number.length < 12; },
        isEmailInvalid() { return this.student.personal_email.length > 0 && !this.student.personal_email.includes('@'); },
        isReferrerEmailInvalid() { return this.placement.referrer_email.length > 0 && !this.placement.referrer_email.includes('@'); },
        restrictScoreInput() { let val = this.academic.current_score.replace(/[^0-9.]/g, ''); const parts = val.split('.'); if (parts.length > 2) val = parts[0] + '.' + parts.slice(1).join(''); let num = parseFloat(val); if (!isNaN(num)) { if (this.academic.grading_system === 'CGPA' && num > 10) val = '10'; if (this.academic.grading_system === 'Percentage' && num > 100) val = '100'; } this.academic.current_score = val; },

        getAllowedFormat(docType) {
            const label = this.documentLabels[docType];
            const rule = this.adminDocumentRules.find(r => r.name === label);
            if (rule && rule.format) {
                let formatStr = rule.format.toLowerCase();
                if (formatStr.includes('.')) return formatStr.replace(/\s/g, ''); 
                
                let exts = [];
                if (formatStr.includes('pdf')) exts.push('.pdf');
                if (formatStr.includes('jpg') || formatStr.includes('jpeg')) exts.push('.jpg', '.jpeg');
                return exts.length > 0 ? exts.join(',') : '.pdf,.jpg,.jpeg';
            }
            return '.pdf,.jpg,.jpeg'; 
        },

        async handleFileUpload(event, docType) {
            const file = event.target.files[0];
            if (!file) {
                this.documents[docType] = null;
                if (docType === this.consentDocumentKey) this.aadhaarConsent = false;
                return;
            }
            
            if (file.size > 2 * 1024 * 1024) { 
                alert(`Upload failed: File exceeds 2MB limit.`); 
                event.target.value = ''; 
                this.documents[docType] = null; 
                if (docType === this.consentDocumentKey) this.aadhaarConsent = false; 
                return; 
            }

            const allowedFormats = this.getAllowedFormat(docType);
            const fileExt = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
            
            if (allowedFormats && !allowedFormats.includes(fileExt) && !(allowedFormats.includes('.jpg') && fileExt === '.jpeg')) {
                alert(`Upload failed: Invalid format. Allowed extensions: ${allowedFormats}`);
                event.target.value = ''; 
                this.documents[docType] = null; 
                if (docType === this.consentDocumentKey) this.aadhaarConsent = false; 
                return;
            }

            // Show it immediately so the UI feels instant...
            this.documents[docType] = { file: file, name: file.name, previewUrl: URL.createObjectURL(file) };
            if (docType === this.consentDocumentKey) this.aadhaarConsent = false; 
            this.saveStatus = new Date().toLocaleTimeString();

            // ...then persist it against the draft, so the file survives to any
            // other machine. Choosing a different file later simply overwrites
            // this one: a draft is not an audit record.
            const stored = await this.uploadDraftDocument(docType, file);
            if (stored) {
                this.documents[docType] = {
                    file: file,
                    name: stored.name,
                    path: stored.path,
                    previewUrl: stored.url ? ('http://127.0.0.1:8000' + stored.url) : URL.createObjectURL(file)
                };
                this.saveStatus = new Date().toLocaleTimeString();
            } else {
                // Upload failed: do not leave a file showing as saved when it is not.
                this.documents[docType] = null;
                event.target.value = '';
                if (docType === this.consentDocumentKey) this.aadhaarConsent = false;
            }
        },

        // Opens the protected viewer in a new tab. Documents uploaded in Phase 1
        // are never served as static files, so there is no direct URL: the link
        // is role-checked, expires, and is recorded in the audit ledger.
        previewDocument(docType) {
            const doc = this.documents[docType];
            if (!doc) return;
            // A file just picked in this session has a local blob URL; one loaded
            // from a draft or a submitted application has a secure viewer URL.
            const url = doc.previewUrl && doc.previewUrl.startsWith('blob:')
                ? doc.previewUrl
                : this.secureDocumentUrl(doc.previewUrl);
            if (url) window.open(url, '_blank', 'noopener');
        },
        
        // Shared with previewDocument: the viewer URL is RELATIVE, so it must be
        // resolved against the Django host. Opening it raw resolved it against
        // the page's own origin (the static server on :5500), which produced a
        // "Cannot GET /api/documents/view/" page.
        secureDocumentUrl(relativeUrl) {
            if (!relativeUrl) return null;
            if (relativeUrl.startsWith('http')) return relativeUrl;
            const suffix = (this.isDevMode && this.devEmployeeCode)
                ? '&emp=' + this.devEmployeeCode : '';
            return 'http://127.0.0.1:8000' + relativeUrl + suffix;
        },

        previewDrawerDocument(docObj) { 
            const url = this.secureDocumentUrl(docObj?.previewUrl);
            if (url) {
                window.open(url, '_blank', 'noopener');
            }
        },
        
        // Counts only documents that are CURRENTLY required. Counting every key
        // in this.documents included files uploaded before a document was
        // disabled mid-draft, producing counts like "6/4".
        getUploadedCount() {
            return this.activeDocumentRules.filter(rule => this.documents[rule.key]).length;
        },

        // Denominator for the vault badge: how many documents apply right now.
        getRequiredCount() { return this.activeDocumentRules.length; },
        getDrawerUploadedCount() { return this.selectedDrawerApp ? Object.values(this.selectedDrawerApp.documents).filter(doc => doc !== null).length : 0; },

        initializeWizard() { if (this.placement.cycle_id) { this.portalState = 'form_wizard'; this.saveStatus = new Date().toLocaleTimeString(); this.unloadGuard = (e) => { e.preventDefault(); e.returnValue = ''; }; window.addEventListener('beforeunload', this.unloadGuard); window.scrollTo({ top: 0, behavior: 'smooth' }); } },

        getStepMissing(step) {
            const missing = []; const blank = (v) => !v || String(v).trim() === '';
            if (step === 1) { [['salutation', 'Title'],['fullName', 'Full Name'],['fathersName', "Father's Name"],['gender', 'Gender'],['dateOfBirth', 'Date of Birth'],['mobile_number', 'Mobile Number'],['personal_email', 'Email ID'],['permanent_address', 'Permanent Address'],['emergency_contact_name', 'Emergency Contact Name'],['emergency_contact_mobile', 'Emergency Contact Mobile']].forEach(([field, label]) => { if (blank(this.student[field])) missing.push(label); }); if (this.student.mobile_number.length > 0 && this.student.mobile_number.length !== 10) missing.push('Mobile Number (must be 10 digits)'); if (this.student.emergency_contact_mobile.length > 0 && this.student.emergency_contact_mobile.length !== 10) missing.push('Emergency Contact Mobile (must be 10 digits)'); if (this.student.personal_email.length > 0 && !this.student.personal_email.includes('@')) missing.push('Valid Email ID (missing @ symbol)'); }
            else if (step === 2) { [['university_name', 'University Name'],['college_name', 'College / Institute Name'],['course', 'Course (Degree)'],['branch', 'Branch / Specialization'],['current_semester', 'Current Semester'],['current_score', 'Current Score']].forEach(([field, label]) => { if (blank(this.academic[field])) missing.push(label); }); if (this.academic.course === 'Other' && blank(this.academic.course_other)) missing.push('Custom Degree Name'); if (this.academic.branch === 'Other' && blank(this.academic.branch_other)) missing.push('Custom Branch Name'); }
            else if (step === 3) { 
                // The identity number is only required when its document is
                // configured; disabling the Aadhaar document removes both.
                if (this.requiresIdentityNumber
                    && (blank(this.student.aadhaar_number) || this.student.aadhaar_number.length !== 12)) {
                    missing.push('Aadhaar Number (must be 12 digits)');
                }

                // Only MANDATORY documents gate submission. An optional document
                // left empty is a legitimate outcome, not an error.
                this.activeDocumentRules.forEach(rule => {
                    if (rule.isMandatory && !this.documents[rule.key]) missing.push(rule.name);
                });
                
                if (this.consentDocumentKey && this.documents[this.consentDocumentKey] && !this.aadhaarConsent) missing.push('Aadhaar Data Consent'); 
            }
            else if (step === 4) { [['department_id', 'Target Department'],['duration_weeks', 'Internship Duration'],['requested_doj', 'Preferred Date of Joining']].forEach(([field, label]) => { if (blank(this.placement[field])) missing.push(label); }); if (!this.placement.isInstitutionalMerge) { if (blank(this.placement.referrer_email)) missing.push('Referrer Official Email ID'); if (this.placement.referrer_email.length > 0 && !this.placement.referrer_email.includes('@')) missing.push('Valid Referrer Email (missing @ symbol)'); } }
            return missing;
        },

        validateCurrentStep() { return this.getStepMissing(this.currentStep).length === 0; },
        get missingByStep() { const groups = []; [1, 2, 3, 4].forEach(step => { const items = this.getStepMissing(step); if (items.length > 0) groups.push({ step: step, title: this.stepTitles[step], items: items }); }); return groups; },
        get isReadyToSubmit() { return this.missingByStep.length === 0; },
        get canSubmit() { return this.isReadyToSubmit && this.acceptedDeclarations; },
        isSectionComplete(step) { return this.getStepMissing(step).length === 0; },
        toggleSection(n) { this.reviewSections[n] = !this.reviewSections[n]; },
        setAllSections(open) { [1, 2, 3, 4].forEach(n => this.reviewSections[n] = open); },
        get allSectionsOpen() { return [1, 2, 3, 4].every(n => this.reviewSections[n]); },

        displayValue(v) { return !v || String(v).trim() === '' ? '—' : v; },
        displayDate(iso) { if (!iso) return '—'; const parts = iso.split('-'); return parts.length === 3 && parts[0].length === 4 ? `${parts[2]}-${parts[1]}-${parts[0]}` : iso; },
        // Puts a STORED value back into a dropdown plus its custom box.
        //
        // Two cases this has to survive. Reopening a saved draft used to restore
        // the selection but not the typed name, so a custom degree came back as
        // "Other" with an empty box. And when HR completes a College Referral,
        // the stored degree may be a custom name that matches no option at all,
        // which left the field blank.
        //
        // Matched without regard to case because stored values are upper case
        // while the options are not.
        applyOption(stored, options) {
            const value = (stored || '').trim();
            if (!value) return { selected: '', other: '' };
            const match = (options || []).find(o => o.toUpperCase() === value.toUpperCase());
            return match ? { selected: match, other: '' }
                         : { selected: 'Other', other: value };
        },

        displayCourse(acadObj = this.academic) { return acadObj.course === 'Other' ? acadObj.course_other : acadObj.course; },
        displayBranch(acadObj = this.academic) { return acadObj.branch === 'Other' ? acadObj.branch_other : acadObj.branch; },
        displayScore(acadObj = this.academic) { return acadObj.current_score ? acadObj.current_score + (acadObj.grading_system === 'CGPA' ? ' CGPA (out of 10)' : '% (Percentage)') : ''; },

        requestSubmit() { if (this.canSubmit) this.showSubmitConfirm = true; },
        
        async submitApplication() {
            this.showSubmitConfirm = false;
            const formData = new FormData();
            formData.append('student', JSON.stringify(this.student)); formData.append('academic', JSON.stringify(this.academic)); formData.append('placement', JSON.stringify(this.placement));
            
            if (this.activeDraftId) {
                // Tells the backend to promote this draft's uploaded documents
                // into the real application, then delete the draft.
                formData.append('draft_id', this.activeDraftId);
            }
            // ticket_id tells the server to UPDATE an existing application
            // rather than create a new one. Two cases reach here:
            //   * a referrer resubmitting a bounced application, and
            //   * HR completing or correcting a College Referral.
            // The server distinguishes them and routes each correctly -- a
            // college referral must not be treated as a resubmission, or it
            // would be dragged out of its section into the main Pending queue.
            if (this.existingTicketId && (this.isCorrectionMode || this.placement.isInstitutionalMerge)) {
                formData.append('ticket_id', this.existingTicketId);
            }
            
            // Only CURRENTLY required documents are sent. A file uploaded before
            // its document was disabled mid-draft is deliberately dropped: it is
            // no longer part of the workflow.
            //
            // The field name carries the NUMERIC doc_type_id. Sending the full
            // key ('doc_12') produced 'document_doc_12', and the backend strips
            // only 'document_', leaving a non-numeric value that failed to
            // resolve -- so the file was silently discarded.
            const liveDocs = {};
            this.activeDocumentRules.forEach(rule => {
                const docObj = this.documents[rule.key];
                if (docObj && docObj.file) {
                    formData.append(`document_${rule.id}`, docObj.file);
                    liveDocs[rule.key] = { name: docObj.name, previewUrl: docObj.previewUrl };
                }
            });

            try {
                const response = await fetch('http://127.0.0.1:8000/api/apply/', { method: 'POST', headers: this.authHeaders(), body: formData });
                if (!response.ok) throw new Error((await response.json()).error || 'Failed to submit application');
                const data = await response.json();

                this.finalTicket = data.ticket_id; this.applicationCode = this.finalTicket; this.submittedAt = new Date().toLocaleString();
                
                // The server deletes the draft as part of promoting it into a real
                // application, so there is nothing to clean up client-side. This
                // used to prune localStorage AFTER the fetch, which meant an
                // interrupted response stranded a duplicate draft forever.
                this.activeDraftId = null;
                this.applications = this.applications.filter(a => a.id !== this.activeDraftId && a.ticketId !== this.existingTicketId);

                // Only for a referrer's own queue. HR completing a college
                // referral is not looking at that list, and adding a row marked
                // 'Submitted' would misdescribe a record that is Ready for Merge.
                if (!this.placement.isInstitutionalMerge) this.applications.unshift({
                    id: Date.now(), tab: 'submitted', status: 'Submitted', badge: 'bg-warning text-dark', ticketId: this.finalTicket, targetCycle: this.activeCycle ? this.activeCycle.name : '—', createdDate: new Date().toLocaleDateString('en-GB').replace(/\//g, '-'), dept: this.placement.department_id || '—', duration: this.placement.duration_weeks ? this.placement.duration_weeks + ' Weeks' : '', doj: this.placement.requested_doj, isWard: this.placement.is_ward, cycle_id: this.placement.cycle_id, referrer_email: this.placement.referrer_email, student: JSON.parse(JSON.stringify(this.student)), academic: JSON.parse(JSON.stringify(this.academic)), documents: liveDocs, timeline: [ { date: new Date().toLocaleDateString('en-GB').replace(/\//g, '-'), title: 'Application Submitted', desc: 'Locked and stored in TiDB cloud.' } ]
                });
                
                if (this.placement.isInstitutionalMerge) {
                    // No cross-tab signalling. The dashboard re-reads the record
                    // from the server when it regains focus, so it always shows
                    // what was actually saved rather than what this tab believed
                    // it saved.
                    const wasCorrection = this.institutionalStatus === 'Ready for Merge';
                    alert(wasCorrection
                        ? `Corrections saved for ${this.finalTicket}.\n\n`
                          + `Return to the HR dashboard to mark the candidate as arrived `
                          + `when they report.`
                        : `${this.finalTicket} is now complete and ready for merge.\n\n`
                          + `Return to the HR dashboard. When the candidate reports, mark `
                          + `them as arrived to move the application into the main pipeline.`);
                }

                if (this.unloadGuard) { window.removeEventListener('beforeunload', this.unloadGuard); this.unloadGuard = null; }
                this.portalState = 'submitted'; window.scrollTo({ top: 0, behavior: 'smooth' });

            } catch (error) { console.error('Submission error:', error); alert(`Submission Failed: ${error.message}\nPlease check your network connection and try again.`); }
        },

        nextStep() { if (this.validateCurrentStep()) this.proceedToNextStep(); else this.showValidationWarning = true; },
        proceedToNextStep() { this.showValidationWarning = false; if (this.currentStep < this.totalSteps) { this.currentStep++; if (this.currentStep > this.highestStepReached) this.highestStepReached = this.currentStep; this.saveStatus = new Date().toLocaleTimeString(); this.autoSaveWip(); } },
        prevStep() { if (this.currentStep > 1) { this.currentStep--; this.saveStatus = new Date().toLocaleTimeString(); this.autoSaveWip(); } },
        goToStep(targetStep) { if (targetStep <= this.highestStepReached) this.currentStep = targetStep; }
    }));
});