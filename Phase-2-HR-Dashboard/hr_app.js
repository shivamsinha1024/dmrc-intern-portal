document.addEventListener('alpine:init', () => {
    Alpine.data('hrCommandCenter', () => ({
        // Global UI State
        isSidebarCollapsed: false,
        activeTab: 'Pending', 
        showFilterDrawer: false,
        selectedApplicant: null,
        
        // Bulk Actions State
        selectedRows: [],
        
        // Modal State for Bulk Evaluation in "Active" tab
        bulkEvaluation: {
            result: '',
            remark: '',
            attendance: false,
            report: false
        },

        // Modal State for Bulk No-Show Warning in "Scheduled" tab
        bulkNoShowData: {
            flagged: [],
            rejected: []
        },

        // Drawer Temp State (For Remarks)
        actionRemark: '',
        showRemarkInput: false,
        pendingActionType: '', 
        
        // Allowed AHR Joining Dates
        allowedDojDatesByCycle: {
            'Summer 2026': ['2026-05-04', '2026-05-11', '2026-05-18', '2026-05-25', '2026-06-08', '2026-06-22'],
            'Winter 2026': ['2026-12-07', '2026-12-14', '2026-12-21', '2026-12-28', '2027-01-11', '2027-01-25']
        },

        getCycleDojDates() {
            if (!this.selectedApplicant) return [];
            return this.allowedDojDatesByCycle[this.selectedApplicant.cycle] || [];
        },

        get availableFilterDojDates() {
            let dates = [];
            if (this.filters.cycle) {
                dates = this.allowedDojDatesByCycle[this.filters.cycle] || [];
            } else {
                Object.values(this.allowedDojDatesByCycle).forEach(arr => {
                    dates = dates.concat(arr);
                });
            }
            return [...new Set(dates)].sort();
        },
        
        // Extended Search & Filter State (Added isCritical)
        masterSearch: '',
        filters: { cycle: '', department: '', specificDoj: '', evaluationResult: '', resubmissionType: '', isWaitlisted: false, isWard: false, isCritical: false },
        sortBy: 'submission_asc',

        // Flatpickr Instance Tracker
        fpInstance: null,

        // Mock Data Database 
        applications: [
            { 
                id: 999, ticket: 'DMRC-2026W-WL-319', name: 'Shivam Sinha', cycle: 'Winter 2026', department: 'IT', 
                status: 'Submitted', date: '2026-07-14', doj: '2026-12-28', waitlisted: true, ward: false, 
                allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'R. Sharma', 
                actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, 
                originalSubmissionDate: '2026-07-14', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null,
                bio: { father: 'Sunil Kumar', gender: 'Male', dob: '29-12-2004', mobile: '7007709797', email: 'shivamsinha10a@gmail.com', address: '6/130, Subhash Nagar, West Delhi, New Delhi. 110027', emergencyName: 'Sunil Kumar', emergencyMobile: '9792120077' },
                academic: { university: 'Guru Gobind Singh Indraprastha University', college: 'Guru Tegh Bahadur Institute of Technology', course: 'B.Tech / B.E.', branch: 'Information Technology', semester: 'Semester 4', grading: 'CGPA (10)', score: '8.8' },
                internship: { duration: '4 Weeks (1 Month)' },
                referrer: { id: 'EMP-4471', designation: 'Senior Engineer', dept: 'Signal & Telecom' },
                docs: { photo: 'Shivam Photograph.jpg', signature: 'Shivam Signature.jpg', aadhar: 'Shivam.pdf', collegeId: 'Student ID Front.jpeg', lor: 'TnP Letter.pdf' }
            },
            { id: 1, ticket: 'DMRC-2026W-001', name: 'Rahul Sharma', cycle: 'Winter 2026', department: 'IT', status: 'Submitted', date: '2026-10-10', doj: '2026-12-07', waitlisted: false, ward: true, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'S. Patel', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, 
              originalSubmissionDate: '2026-09-25', hasUsedDocumentLifeline: true, documentResubmissionDetails: { date: '2026-10-10', issue: 'Aadhar Card blurred/unreadable' }, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 2, ticket: 'DMRC-2026W-WL-089', name: 'Priya Patel', cycle: 'Winter 2026', department: 'Civil', status: 'Submitted', date: '2026-10-11', doj: '2026-12-14', waitlisted: true, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'A. Gupta', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-11', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 3, ticket: 'DMRC-2026W-045', name: 'Amit Kumar', cycle: 'Winter 2026', department: 'Electrical', status: 'Approved', date: '2026-10-09', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'M. Singh', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-09', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 4, ticket: 'DMRC-2026W-012', name: 'Neha Singh', cycle: 'Winter 2026', department: 'IT', status: 'Rejected', date: '2026-10-08', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'L. Kumar', actualDoj: null, dateOfCompletion: null, dateOfRejection: '2026-10-12', rejectionReason: 'Invalid Document', originalSubmissionDate: '2026-10-08', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 5, ticket: 'DMRC-2026W-077', name: 'Vikram Verma', cycle: 'Winter 2026', department: 'S&T', status: 'Pending Clearance', date: '2026-10-05', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: '2026-12-07', evaluationResult: 'Satisfactory', evaluationRemark: 'Good progress.', attendanceCleared: true, reportCleared: true, referrerName: 'T. Rao', actualDoj: '2026-12-07', dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-05', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 6, ticket: 'DMRC-2026W-112', name: 'Sanya Gupta', cycle: 'Winter 2026', department: 'IT', status: 'Scheduled', date: '2026-10-07', doj: '2026-12-14', waitlisted: false, ward: false, allottedDoj: '2026-12-14', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'K. Desai', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-07', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 7, ticket: 'DMRC-2026W-201', name: 'Pooja Mishra', cycle: 'Winter 2026', department: 'Civil', status: 'Completed', date: '2026-09-15', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: '2026-12-07', evaluationResult: 'Satisfactory', evaluationRemark: 'Excellent work and punctuality.', attendanceCleared: true, reportCleared: true, referrerName: 'J. Doe', actualDoj: '2026-12-07', dateOfCompletion: '2027-01-15', dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-15', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 8, ticket: 'DMRC-2026W-134', name: 'Rohan Das', cycle: 'Winter 2026', department: 'Mechanical/RS', status: 'Submitted', date: '2026-10-12', doj: '2026-12-21', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'P. Verma', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, 
              originalSubmissionDate: '2026-09-20', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: true, dojResubmissionDetails: { date: '2026-10-12', issue: 'Missed original joining date (No-Show)', previousDoj: '2026-12-07' }, bio: null },
            { id: 9, ticket: 'DMRC-2026W-099', name: 'Aisha Khan', cycle: 'Winter 2026', department: 'Finance', status: 'Scheduled', date: '2026-10-06', doj: '2026-12-07', waitlisted: false, ward: true, allottedDoj: '2026-12-07', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'R. Khan', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-06', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 10, ticket: 'DMRC-2026W-155', name: 'Karan Malhotra', cycle: 'Winter 2026', department: 'HR', status: 'Approved', date: '2026-10-11', doj: '2026-12-14', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'M. Joshi', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-11', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 11, ticket: 'DMRC-2026W-180', name: 'Sneha Reddy', cycle: 'Winter 2026', department: 'Legal', status: 'Joined', date: '2026-10-01', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: '2026-12-07', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'V. Rathi', actualDoj: '2026-12-07', dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-01', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 12, ticket: 'DMRC-2026W-119', name: 'Manish Tiwari', cycle: 'Winter 2026', department: 'Mechanical/RS', status: 'Scheduled', date: '2026-10-08', doj: '2026-12-21', waitlisted: false, ward: false, allottedDoj: '2026-12-21', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'T. Sharma', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-08', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 13, ticket: 'DMRC-2026W-105', name: 'Arjun Nair', cycle: 'Winter 2026', department: 'S&T', status: 'Submitted', date: '2026-10-11', doj: '2026-12-28', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'B. Singh', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-11', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 14, ticket: 'DMRC-2026W-050', name: 'Zara Ahmed', cycle: 'Winter 2026', department: 'Electrical', status: 'Completed', date: '2026-09-10', doj: '2026-12-07', waitlisted: false, ward: true, allottedDoj: '2026-12-07', evaluationResult: 'Unsatisfactory', evaluationRemark: 'Incomplete assignments and poor attendance.', attendanceCleared: true, reportCleared: true, referrerName: 'S. Ahmed', actualDoj: '2026-12-07', dateOfCompletion: '2027-01-10', dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-10', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 15, ticket: 'DMRC-2026W-244', name: 'Vikas Singh', cycle: 'Winter 2026', department: 'Civil', status: 'Submitted', date: '2026-10-15', doj: '2026-12-28', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'D. Kumar', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, 
              originalSubmissionDate: '2026-08-01', hasUsedDocumentLifeline: true, documentResubmissionDetails: { date: '2026-08-15', issue: 'Invalid Signature File' }, hasUsedDojLifeline: true, dojResubmissionDetails: { date: '2026-10-15', issue: 'Missed original joining date (No-Show)', previousDoj: '2026-09-01' }, bio: null }, 
            { id: 16, ticket: 'DMRC-2026W-301', name: 'Siddharth Jain', cycle: 'Winter 2026', department: 'IT', status: 'Scheduled', date: '2026-10-12', doj: '2026-12-14', waitlisted: false, ward: false, allottedDoj: '2026-12-14', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'A. Sharma', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, 
              originalSubmissionDate: '2026-09-10', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: true, dojResubmissionDetails: { date: '2026-10-12', issue: 'Missed joining date', previousDoj: '2026-09-25' }, bio: null }, 
            { id: 17, ticket: 'DMRC-2026W-199', name: 'Tanya Goel', cycle: 'Winter 2026', department: 'HR', status: 'Approved', date: '2026-10-09', doj: '2026-12-14', waitlisted: false, ward: true, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'R. Goel', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-09', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 18, ticket: 'DMRC-2026W-088', name: 'Ravi Teja', cycle: 'Winter 2026', department: 'Electrical', status: 'Pending Clearance', date: '2026-09-12', doj: '2026-12-07', waitlisted: true, ward: false, allottedDoj: '2026-12-07', evaluationResult: 'Unsatisfactory', evaluationRemark: 'Missed 3 days without notice.', attendanceCleared: true, reportCleared: true, referrerName: 'S. Nandi', actualDoj: '2026-12-07', dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-12', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 19, ticket: 'DMRC-2026W-405', name: 'Nidhi Agarwal', cycle: 'Winter 2026', department: 'Finance', status: 'Joined', date: '2026-09-28', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: '2026-12-07', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'P. Jain', actualDoj: '2026-12-07', dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-28', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 20, ticket: 'DMRC-2026W-311', name: 'Omar Farooq', cycle: 'Winter 2026', department: 'Mechanical/RS', status: 'Rejected', date: '2026-09-05', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'H. Khan', actualDoj: null, dateOfCompletion: null, dateOfRejection: '2026-10-02', rejectionReason: 'Repeated Invalid Documents', 
              originalSubmissionDate: '2026-08-15', hasUsedDocumentLifeline: true, documentResubmissionDetails: { date: '2026-09-05', issue: 'Missing LOR' }, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null }, 
            { id: 21, ticket: 'DMRC-2026W-289', name: 'Lakshay Sharma', cycle: 'Winter 2026', department: 'IT', status: 'Scheduled', date: '2026-10-15', doj: '2026-12-28', waitlisted: false, ward: true, allottedDoj: '2026-12-28', evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'K. Sharma', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-15', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 22, ticket: 'DMRC-2026W-412', name: 'Deepak Chopra', cycle: 'Winter 2026', department: 'Civil', status: 'Submitted', date: '2026-10-14', doj: '2026-12-14', waitlisted: false, ward: false, allottedDoj: null, evaluationResult: '', evaluationRemark: '', attendanceCleared: false, reportCleared: false, referrerName: 'M. Mehta', actualDoj: null, dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-10-14', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 23, ticket: 'DMRC-2026W-290', name: 'Kavita Singh', cycle: 'Winter 2026', department: 'Legal', status: 'Completed', date: '2026-09-01', doj: '2026-12-07', waitlisted: false, ward: false, allottedDoj: '2026-12-07', evaluationResult: 'Satisfactory', evaluationRemark: 'Drafted 5 contracts flawlessly.', attendanceCleared: true, reportCleared: true, referrerName: 'A. Rajput', actualDoj: '2026-12-07', dateOfCompletion: '2027-01-11', dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-01', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null },
            { id: 24, ticket: 'DMRC-2026W-033', name: 'Ananya Roy', cycle: 'Winter 2026', department: 'S&T', status: 'Pending Clearance', date: '2026-09-18', doj: '2026-12-14', waitlisted: false, ward: true, allottedDoj: '2026-12-14', evaluationResult: 'Satisfactory', evaluationRemark: 'Excellent team player.', attendanceCleared: true, reportCleared: true, referrerName: 'B. Roy', actualDoj: '2026-12-14', dateOfCompletion: null, dateOfRejection: null, rejectionReason: null, originalSubmissionDate: '2026-09-18', hasUsedDocumentLifeline: false, documentResubmissionDetails: null, hasUsedDojLifeline: false, dojResubmissionDetails: null, bio: null }
        ],

        init() {
            this.$watch('activeTab', () => {
                this.selectedRows = [];
            });
        },

        getLatestResubDate(app) {
            let d1 = app.documentResubmissionDetails?.date ? new Date(app.documentResubmissionDetails.date) : null;
            let d2 = app.dojResubmissionDetails?.date ? new Date(app.dojResubmissionDetails.date) : null;
            if (d1 && d2) return d1 > d2 ? d1 : d2;
            return d1 || d2 || null;
        },

        get processedQueue() {
            let result = this.applications;

            if (this.activeTab !== 'All') {
                if (this.activeTab === 'Pending') result = result.filter(app => app.status === 'Submitted' || app.status === 'Under Verification');
                else if (this.activeTab === 'Resubmissions') result = result.filter(app => app.hasUsedDocumentLifeline || app.hasUsedDojLifeline);
                else if (this.activeTab === 'Active') result = result.filter(app => app.status === 'Joined');
                else if (this.activeTab === 'Final Review') result = result.filter(app => app.status === 'Pending Clearance');
                else result = result.filter(app => app.status === this.activeTab);
            }

            if (this.filters.cycle) result = result.filter(app => app.cycle === this.filters.cycle);
            if (this.filters.department) result = result.filter(app => app.department === this.filters.department);
            if (this.filters.specificDoj) result = result.filter(app => app.doj === this.filters.specificDoj);
            if (this.filters.evaluationResult) result = result.filter(app => app.evaluationResult === this.filters.evaluationResult);
            if (this.filters.isWaitlisted) result = result.filter(app => app.waitlisted === true);
            if (this.filters.isWard) result = result.filter(app => app.ward === true);
            
            if (this.filters.resubmissionType === 'Document') result = result.filter(app => app.hasUsedDocumentLifeline);
            if (this.filters.resubmissionType === 'DOJ') result = result.filter(app => app.hasUsedDojLifeline);
            
            // NEW: Critical Lifelines Exhausted Filter
            if (this.filters.isCritical) result = result.filter(app => app.hasUsedDocumentLifeline && app.hasUsedDojLifeline);

            if (this.masterSearch.trim() !== '') {
                const query = this.masterSearch.toLowerCase();
                result = result.filter(app => app.ticket.toLowerCase().includes(query) || app.name.toLowerCase().includes(query) || app.referrerName.toLowerCase().includes(query));
            }

            return result.sort((a, b) => {
                let dateA = new Date(a.date);
                let dateB = new Date(b.date);
                
                if (this.sortBy === 'submission_asc') return dateA - dateB;
                if (this.sortBy === 'submission_desc') return dateB - dateA;
                if (this.sortBy === 'doj_asc') return new Date(a.doj) - new Date(b.doj);
                if (this.sortBy === 'resubmission_desc') {
                    let rDateA = this.getLatestResubDate(a) || dateA;
                    let rDateB = this.getLatestResubDate(b) || dateB;
                    return rDateB - rDateA;
                }
                return 0;
            });
        },

        formatDate(isoString) {
            if (!isoString) return '—';
            const parts = isoString.split('-');
            if(parts.length !== 3) return isoString; 
            return `${parts[2]}-${parts[1]}-${parts[0]}`;
        },

        clearFilters() {
            this.filters = { cycle: '', department: '', specificDoj: '', evaluationResult: '', resubmissionType: '', isWaitlisted: false, isWard: false, isCritical: false };
            this.masterSearch = '';
        },

        toggleAllRows(event) {
            this.selectedRows = event.target.checked ? this.processedQueue.map(app => app.ticket) : [];
        },

        bulkAction(actionType) {
            if (this.selectedRows.length === 0) return;
            alert(`Bulk Workflow Triggered: [${actionType}] successfully applied to ${this.selectedRows.length} candidates.\n\nAffected Tickets:\n${this.selectedRows.join('\n')}`);
            this.selectedRows = []; 
        },

        triggerBulkNoShow() {
            this.bulkNoShowData.flagged = [];
            this.bulkNoShowData.rejected = [];
            
            this.selectedRows.forEach(ticket => {
                const app = this.applications.find(a => a.ticket === ticket);
                if (app.hasUsedDojLifeline) {
                    this.bulkNoShowData.rejected.push(ticket);
                } else {
                    this.bulkNoShowData.flagged.push(ticket);
                }
            });
            
            const modal = new bootstrap.Modal(document.getElementById('bulkNoShowModal'));
            modal.show();
        },

        confirmBulkNoShow() {
            let msg = `Bulk Workflow Executed:\n`;
            if (this.bulkNoShowData.flagged.length > 0) {
                msg += `- ${this.bulkNoShowData.flagged.length} candidates Flagged for Resubmission (Lifeline Available).\n`;
            }
            if (this.bulkNoShowData.rejected.length > 0) {
                msg += `- ${this.bulkNoShowData.rejected.length} candidates Automatically Rejected (Lifeline Exhausted).\n`;
            }
            alert(msg);
            this.selectedRows = [];
            bootstrap.Modal.getInstance(document.getElementById('bulkNoShowModal')).hide();
        },

        openBulkActiveModal() {
            this.bulkEvaluation = { result: '', remark: '', attendance: false, report: false };
            const modal = new bootstrap.Modal(document.getElementById('bulkActiveModal'));
            modal.show();
        },

        confirmBulkActive() {
            alert(`Bulk Workflow Triggered: Applied evaluation to ${this.selectedRows.length} candidates and moved them to Final Review.\n\nResult: ${this.bulkEvaluation.result}\nDocuments Cleared: Yes`);
            this.selectedRows = [];
            bootstrap.Modal.getInstance(document.getElementById('bulkActiveModal')).hide();
        },

        exportData(format) {
            alert(`Simulating WYSIWYG Export of current view to ${format} format...`);
        },
        
        openApplicantDrawer(ticketId) {
            this.selectedApplicant = null;

            this.$nextTick(() => {
                this.selectedApplicant = this.applications.find(a => a.ticket === ticketId);
                
                if (!this.selectedApplicant.allottedDoj) {
                    this.selectedApplicant.allottedDoj = this.selectedApplicant.doj;
                }

                this.showRemarkInput = false;
                this.actionRemark = '';
                this.pendingActionType = '';

                const offcanvasEl = document.getElementById('applicantDrawer');
                let offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
                if (!offcanvas) {
                    offcanvas = new bootstrap.Offcanvas(offcanvasEl);
                }
                offcanvas.show();
            });
        },

        isNonStandardDoj() {
            if (!this.selectedApplicant || !this.selectedApplicant.allottedDoj) return false;
            const checkDate = String(this.selectedApplicant.allottedDoj).trim();
            return !this.getCycleDojDates().includes(checkDate);
        },

        initCalendar(element) {
            if (this.fpInstance) {
                this.fpInstance.destroy(); 
            }
            
            this.fpInstance = flatpickr(element, {
                dateFormat: 'Y-m-d',
                altInput: true,
                altFormat: 'd-m-Y',
                defaultDate: this.selectedApplicant.allottedDoj,
                disable: [
                    (date) => date.getDay() === 0 || date.getDay() === 6
                ],
                onDayCreate: (dObj, dStr, fp, dayElem) => {
                    let y = dayElem.dateObj.getFullYear();
                    let m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                    let d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                    
                    if (this.getCycleDojDates().includes(`${y}-${m}-${d}`)) {
                        dayElem.classList.add('ahr-approved-date');
                    }
                },
                onChange: (selectedDates) => {
                    if (selectedDates.length > 0) {
                        let d = selectedDates[0];
                        let y = d.getFullYear();
                        let m = String(d.getMonth() + 1).padStart(2, '0');
                        let day = String(d.getDate()).padStart(2, '0');
                        
                        this.selectedApplicant.allottedDoj = `${y}-${m}-${day}`;
                    } else {
                        this.selectedApplicant.allottedDoj = null;
                    }
                }
            });
        },

        triggerRemarkAction(actionType, autoFillContext = null) {
            this.pendingActionType = actionType;
            this.showRemarkInput = true;
            
            if (autoFillContext === 'Repeated Document') {
                this.actionRemark = 'Repeated Invalid Documents. Lifeline exhausted.';
            } else if (autoFillContext === 'Repeated DOJ') {
                this.actionRemark = 'Repeated No-Show. Lifeline exhausted.';
            } else {
                this.actionRemark = '';
            }
        },

        cancelRemarkAction() {
            this.showRemarkInput = false;
            this.actionRemark = '';
            this.pendingActionType = '';
        },

        confirmAction(action) {
            if (!this.selectedApplicant) return;
            
            let message = `System Workflow Triggered: [${action}] for ${this.selectedApplicant.ticket}`;
            if (this.showRemarkInput && this.actionRemark.trim() !== '') {
                message += `\nHR Remarks Logged: "${this.actionRemark}"`;
            } else if (this.showRemarkInput) {
                message += `\nHR Remarks: [Blank - Applied Default Tag]`;
            }

            if (action === 'Schedule') {
                message += `\nDOJ Locked: ${this.formatDate(this.selectedApplicant.allottedDoj)}`;
            } else if (action === 'Submit for Final Review' || action === 'Finalize Completion') {
                message += `\nFinal Evaluation: ${this.selectedApplicant.evaluationResult}`;
                if (this.selectedApplicant.evaluationRemark) {
                    message += `\nMentor Remarks: ${this.selectedApplicant.evaluationRemark}`;
                }
            }

            alert(message);
            
            const offcanvasEl = document.getElementById('applicantDrawer');
            const offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
            if(offcanvas) offcanvas.hide();
        },

        handleFileUpload(event) {
            const file = event.target.files[0];
            if (this.selectedApplicant) {
                this.selectedApplicant.evaluationFile = file ? file.name : null;
            }
        }
    }));
});