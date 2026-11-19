import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { History as HistoryIcon, RotateCcw } from 'lucide-react';
import { useSession } from '../context/SessionContext';
import { submitInput, fetchSessionDetails } from '../api';
import SearchableMultiSelect from './SearchableMultiSelect';
import { APOLLO_SIGNALS } from '../constants/apolloSignals';

const FUNDING_OPTIONS = [
    'Seed',
    'Angel',
    'Venture (Round not Specified)',
    'Series A',
    'Series B',
    'Series C',
    'Series D',
    'Series E',
    'Series F',
    'Debt Financing',
    'Equity Crowdfunding',
    'Convertible Note',
    'Private Equity',
    'Merger / Acquisition',
    'Other',
];

function InputForm() {
    const navigate = useNavigate();
    const location = useLocation();
    const queryClient = useQueryClient();
    const { activeSessionId, setActiveSessionId, setActiveSession, activeSessionData } = useSession();

    const [loadedFromSession, setLoadedFromSession] = useState(null);
    const dismissedRef = useRef(false);

    const [formData, setFormData] = useState({
        ourCompanyName: '',
        ourServices: '',
        targetLocation: '',
        targetIndustries: '',
        targetCompanySize: '',
        targetKeywords: '',
        companyLookalike: '',
        signals: [],
        fundingStages: [],
        targetJobTitles: '',
    });

    const [status, setStatus] = useState({ type: '', message: '' });
    const [submitting, setSubmitting] = useState(false);

    const populateFormFromItem = (item) => {
        if (!item) return;

        // Parse comma-separated signals into an array for SearchableMultiSelect
        let parsedSignals = [];
        if (Array.isArray(item.signals)) {
            parsedSignals = item.signals;
        } else if (typeof item.signals === 'string' && item.signals.trim()) {
            parsedSignals = item.signals.split(',').map(s => s.trim()).filter(Boolean);
        }

        // Parse comma-separated funding stages into an array
        let parsedFunding = [];
        if (Array.isArray(item.funding_stages)) {
            parsedFunding = item.funding_stages;
        } else if (typeof item.funding_stages === 'string' && item.funding_stages.trim()) {
            parsedFunding = item.funding_stages.split(',').map(s => s.trim()).filter(Boolean);
        }

        setFormData({
            ourCompanyName: item.our_company_name || '',
            ourServices: item.our_services || '',
            targetLocation: item.target_location || '',
            targetIndustries: item.target_industries || '',
            targetCompanySize: item.target_company_size || '',
            targetKeywords: item.target_keywords || '',
            companyLookalike: item.company_lookalike || '',
            signals: parsedSignals,
            fundingStages: parsedFunding,
            targetJobTitles: item.target_job_titles || '',
        });

        setLoadedFromSession({
            id: item.id,
            companyName: item.our_company_name,
        });
        dismissedRef.current = false;
    };

    // Auto-populate when navigating from History or when active session is present
    useEffect(() => {
        if (location.state?.loadHistoryItem) {
            populateFormFromItem(location.state.loadHistoryItem);
        } else if (activeSessionData && !loadedFromSession && !dismissedRef.current) {
            populateFormFromItem(activeSessionData);
        } else if (activeSessionId && !loadedFromSession && !dismissedRef.current) {
            fetchSessionDetails(activeSessionId)
                .then(data => {
                    if (data && !dismissedRef.current) {
                        populateFormFromItem(data);
                    }
                })
                .catch(err => {
                    console.warn('Could not auto-load active session details into form:', err);
                });
        }
    }, [location.state, activeSessionData, activeSessionId]);

    const handleResetForm = () => {
        dismissedRef.current = true;
        setLoadedFromSession(null);
        setFormData({
            ourCompanyName: '',
            ourServices: '',
            targetLocation: '',
            targetIndustries: '',
            targetCompanySize: '',
            targetKeywords: '',
            companyLookalike: '',
            signals: [],
            fundingStages: [],
            targetJobTitles: '',
        });
        setStatus({
            type: 'info',
            message: 'Form cleared to blank. You can define a brand new search.',
        });
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setStatus({ type: '', message: '' });

        // Validate and normalize Company Look-alike (comma-separated, max 5, remove duplicates)
        const rawLookalikes = formData.companyLookalike
            ? formData.companyLookalike.split(',').map(s => s.trim()).filter(Boolean)
            : [];
        const seen = new Set();
        const normalizedLookalikes = [];
        for (const comp of rawLookalikes) {
            const lower = comp.toLowerCase();
            if (!seen.has(lower)) {
                seen.add(lower);
                normalizedLookalikes.push(comp);
            }
        }

        if (normalizedLookalikes.length > 5) {
            setStatus({
                type: 'error',
                message: 'A maximum of 5 reference companies is supported for Company Look-alike.',
            });
            setSubmitting(false);
            return;
        }

        // Convert camelCase form state -> snake_case expected by backend
        const payload = {
            our_company_name: formData.ourCompanyName.trim(),
            our_services: formData.ourServices.trim(),
            target_location: formData.targetLocation.trim(),
            target_industries: formData.targetIndustries.trim(),
            target_company_size: formData.targetCompanySize.trim(),
            target_keywords: formData.targetKeywords.trim(),
            company_lookalike: normalizedLookalikes.join(', '),
            signals: (formData.signals || []).join(', '),
            funding_stages: (formData.fundingStages || []).join(', '),
            target_job_titles: formData.targetJobTitles.trim(),
            user_input_id: loadedFromSession?.id || null,
        };

        try {
            const data = await submitInput(payload);
            console.log('Input saved successfully:', data);

            if (data?.user_input_id) {
                if (setActiveSession) {
                    setActiveSession({
                        id: data.user_input_id,
                        our_company_name: payload.our_company_name,
                        ...payload,
                    });
                } else if (setActiveSessionId) {
                    setActiveSessionId(data.user_input_id);
                }
            }

            // Invalidate queries so dependent pages refresh immediately
            queryClient.invalidateQueries({ queryKey: ['input-history'] });
            queryClient.invalidateQueries({ queryKey: ['active-session'] });
            queryClient.invalidateQueries({ queryKey: ['overview'] });
            queryClient.invalidateQueries({ queryKey: ['contacts'] });
            queryClient.invalidateQueries({ queryKey: ['notifications'] });

            setStatus({
                type: 'success',
                message: loadedFromSession?.id
                    ? 'Search criteria updated! Discovering and appending new prospects...'
                    : 'Offering and ICP saved! Initializing GTM pipeline...',
            });

            setTimeout(() => {
                navigate('/agents', { state: { runId: data.workflow_run_id } });
            }, 1200);
        } catch (err) {
            console.error('Submit failed:', err);
            setStatus({
                type: 'error',
                message: err?.message || 'Failed to submit input. Please check the values and try again.',
            });
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="w-full space-y-6 pb-12 selection:bg-[#5B4EFF]/15">
            {/* ── Page Header ── */}
            <div>
                <h1 className="text-2xl font-bold text-[#111827] tracking-tight">
                    Input
                </h1>
                <p className="text-xs text-gray-400 font-medium mt-1">
                    Define your offering and ideal customer profile to feed the GTM pipeline
                </p>
            </div>

            {/* ── Main Form Card ── */}
            <div className="bg-white rounded-3xl border border-gray-100 shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-10">
                <form onSubmit={handleSubmit} className="space-y-5 sm:space-y-6">
                    {/* Loaded from Past Search History Banner */}
                    {loadedFromSession && (
                        <div className="bg-[#EEF2FF] border border-[#C7D2FE] rounded-2xl p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs shadow-2xs">
                            <div className="flex items-center gap-2.5">
                                <span className="p-1.5 rounded-lg bg-indigo-600 text-white flex items-center justify-center shadow-xs shrink-0">
                                    <HistoryIcon size={14} />
                                </span>
                                <div>
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="font-semibold text-[#312E81]">
                                            Editing Past Search
                                        </span>
                                        {loadedFromSession.companyName && (
                                            <span className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-md font-medium text-[11px]">
                                                {loadedFromSession.companyName}
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-[11px] text-gray-500 font-normal mt-0.5">
                                        Past search criteria loaded. You can tweak any values and submit to re-run research.
                                    </p>
                                </div>
                            </div>

                            <button
                                type="button"
                                onClick={handleResetForm}
                                className="self-start sm:self-center shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-gray-300 bg-white hover:bg-gray-50 text-gray-700 text-xs font-medium transition-colors shadow-2xs cursor-pointer"
                                title="Clear all fields to start an empty search"
                            >
                                <RotateCcw size={12} className="text-gray-500" />
                                <span>Clear to Blank Form</span>
                            </button>
                        </div>
                    )}

                    {/* Status Alert */}
                    {status.message && (
                        <div
                            className={`p-4 rounded-xl text-xs font-semibold border transition-all ${
                                status.type === 'success'
                                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200/80'
                                    : status.type === 'info'
                                    ? 'bg-blue-50 text-blue-700 border-blue-200/80'
                                    : 'bg-red-50 text-red-700 border-red-200/80'
                            }`}
                        >
                            {status.message}
                        </div>
                    )}

                    {/* 1. Our Company Name * */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Our Company Name <span className="text-[#EF4444] font-bold">*</span>
                        </label>
                        <input
                            type="text"
                            name="ourCompanyName"
                            value={formData.ourCompanyName}
                            onChange={handleChange}
                            placeholder="e.g. CloudLabs"
                            required
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                    </div>

                    {/* 2. Our Services * */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Our Services <span className="text-[#EF4444] font-bold">*</span>
                        </label>
                        <input
                            type="text"
                            name="ourServices"
                            value={formData.ourServices}
                            onChange={handleChange}
                            placeholder="e.g. AI Consulting, Cloud Migration"
                            required
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                        <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                            Used for email personalisation only — not sent to Apollo search
                        </p>
                    </div>

                    {/* 3. Target Location * */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Target Location <span className="text-[#EF4444] font-bold">*</span>
                        </label>
                        <input
                            type="text"
                            name="targetLocation"
                            value={formData.targetLocation}
                            onChange={handleChange}
                            placeholder="e.g. United States, India"
                            required
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                    </div>

                    {/* 4. Target Industries (Optional) */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Target Industries <span className="text-gray-400 font-normal">(Optional)</span>
                        </label>
                        <input
                            type="text"
                            name="targetIndustries"
                            value={formData.targetIndustries}
                            onChange={handleChange}
                            placeholder="e.g. SaaS, Fintech, Healthcare"
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                        <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                            Leave blank to search across all industries
                        </p>
                    </div>

                    {/* 5. Target Company Size * */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Target Company Size <span className="text-[#EF4444] font-bold">*</span>
                        </label>
                        <input
                            type="text"
                            name="targetCompanySize"
                            value={formData.targetCompanySize}
                            onChange={handleChange}
                            placeholder="e.g. 50-5000  (min employees – max employees)"
                            required
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                        <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                            All company sizes within this range will be included
                        </p>
                    </div>

                    {/* 6. Target Keywords (Optional) */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Target Keywords <span className="text-gray-400 font-normal">(Optional)</span>
                        </label>
                        <input
                            type="text"
                            name="targetKeywords"
                            value={formData.targetKeywords}
                            onChange={handleChange}
                            placeholder="e.g. kubernetes, machine learning, digital transformation"
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                        <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                            Signals used to narrow prospect companies
                        </p>
                    </div>

                    {/* Company Look-alike */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Company Look-alike <span className="text-gray-400 font-normal">(Optional)</span>
                        </label>
                        <input
                            type="text"
                            name="companyLookalike"
                            value={formData.companyLookalike}
                            onChange={handleChange}
                            placeholder="e.g. Google, RadNet, Salesforce"
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm"
                        />
                        <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                            Find prospects at companies similar to your reference companies.
                        </p>
                    </div>

                    {/* Signals Filter */}
                    <SearchableMultiSelect
                        label="Signals"
                        options={APOLLO_SIGNALS}
                        selectedValues={formData.signals}
                        onChange={(vals) => setFormData(prev => ({ ...prev, signals: vals }))}
                        placeholder="Select Apollo signals (e.g. Recent funding, Office expansion, High buying intent)..."
                        helperText="Target accounts exhibiting verified company buying triggers (evaluated using OR logic where supported)."
                    />

                    {/* Funding Filter */}
                    <SearchableMultiSelect
                        label="Funding"
                        options={FUNDING_OPTIONS}
                        selectedValues={formData.fundingStages}
                        onChange={(vals) => setFormData(prev => ({ ...prev, fundingStages: vals }))}
                        placeholder="Select funding stages (e.g. Seed, Series A)..."
                        helperText="Select one or more stages without default minimum amount restrictions (evaluated using OR logic)."
                    />

                    {/* 8. Target Job Titles * */}
                    <div>
                        <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                            Target Job Titles <span className="text-[#EF4444] font-bold">*</span>
                        </label>
                        <textarea
                            name="targetJobTitles"
                            value={formData.targetJobTitles}
                            onChange={handleChange}
                            placeholder="e.g. CTO, VP Engineering, Head of AI"
                            required
                            rows={3}
                            className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus:border-[#5B4EFF] rounded-xl py-3 px-4 text-xs sm:text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/15 transition-all shadow-sm resize-none min-h-[90px]"
                        />
                    </div>

                    {/* ── Submit Action Button (Centered) ── */}
                    <div className="flex justify-center pt-4">
                        <button
                            type="submit"
                            disabled={submitting}
                            className="w-full max-w-sm py-3.5 px-8 bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.99] text-white font-semibold text-xs sm:text-sm rounded-xl shadow-[0_4px_14px_rgba(91,78,255,0.25)] transition-all cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {submitting ? (
                                <>
                                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    <span>{loadedFromSession?.id ? 'Updating Search...' : 'Starting GTM Pipeline...'}</span>
                                </>
                            ) : (
                                <span>{loadedFromSession?.id ? 'Update & Re-run Search' : 'Start GTM Pipeline'}</span>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

export default InputForm;