import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from '../context/SessionContext';
import { submitInput } from '../api';

function InputForm() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const { setActiveSessionId } = useSession();

    const [formData, setFormData] = useState({
        ourCompanyName: '',
        ourServices: '',
        targetLocation: '',
        targetIndustries: '',
        targetCompanySize: '',
        targetKeywords: '',
        targetJobTitles: '',
    });

    const [status, setStatus] = useState({ type: '', message: '' });
    const [submitting, setSubmitting] = useState(false);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setStatus({ type: '', message: '' });

        // Convert camelCase form state -> snake_case expected by backend
        const payload = {
            our_company_name: formData.ourCompanyName.trim(),
            our_services: formData.ourServices.trim(),
            target_location: formData.targetLocation.trim(),
            target_industries: formData.targetIndustries.trim(),
            target_company_size: formData.targetCompanySize.trim(),
            target_keywords: formData.targetKeywords.trim(),
            target_job_titles: formData.targetJobTitles.trim(),
        };

        try {
            const data = await submitInput(payload);
            console.log('Input saved successfully:', data);

            if (data?.user_input_id && setActiveSessionId) {
                setActiveSessionId(data.user_input_id);
            }

            // Invalidate queries so dependent pages refresh immediately
            queryClient.invalidateQueries({ queryKey: ['input-history'] });
            queryClient.invalidateQueries({ queryKey: ['active-session'] });
            queryClient.invalidateQueries({ queryKey: ['overview'] });
            queryClient.invalidateQueries({ queryKey: ['contacts'] });
            queryClient.invalidateQueries({ queryKey: ['notifications'] });

            setStatus({
                type: 'success',
                message: 'Offering and ICP saved! Initializing GTM pipeline...',
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
                    {/* Status Alert */}
                    {status.message && (
                        <div
                            className={`p-4 rounded-xl text-xs font-semibold border transition-all ${
                                status.type === 'success'
                                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200/80'
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

                    {/* 7. Target Job Titles * */}
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
                                    <span>Starting GTM Pipeline...</span>
                                </>
                            ) : (
                                <span>Start GTM Pipeline</span>
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

export default InputForm;