import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSession } from '../context/SessionContext';

function InputForm() {
    const navigate = useNavigate();
    const { setActiveSessionId } = useSession();
    const [formData, setFormData] = useState({
        ourCompanyName:     '',
        ourServices:        '',
        targetLocation:     '',
        targetIndustries:   '',   // optional
        targetCompanySize:  '',
        targetKeywords:     '',   // optional
        targetJobTitles:    '',
    });
    const [status, setStatus] = useState({ type: '', message: '' });
    const [submitting, setSubmitting] = useState(false);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData({ ...formData, [name]: value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        setStatus({ type: '', message: '' });

        // Convert camelCase form state -> snake_case expected by FastAPI
        const payload = {
            our_company_name:    formData.ourCompanyName,
            our_services:        formData.ourServices,
            target_location:     formData.targetLocation,
            target_industries:   formData.targetIndustries,   // may be ""
            target_company_size: formData.targetCompanySize,
            target_keywords:     formData.targetKeywords,     // may be ""
            target_job_titles:   formData.targetJobTitles,
        };

        try {
            const response = await fetch('/api/v1/submit-input', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                throw new Error(`Request failed: ${response.status}`);
            }

            const data = await response.json();
            console.log('Saved:', data);
            if (data.user_input_id && setActiveSessionId) {
                setActiveSessionId(data.user_input_id);
            }
            setStatus({ type: 'success', message: 'Details submitted! Redirecting to Agent Control...' });

            // Reset form
            setFormData({
                ourCompanyName:     '',
                ourServices:        '',
                targetLocation:     '',
                targetIndustries:   '',
                targetCompanySize:  '',
                targetKeywords:     '',
                targetJobTitles:    '',
            });

            setTimeout(() => {
                navigate('/agents', { state: { runId: data.workflow_run_id } });
            }, 1500);
        } catch (err) {
            console.error('Submit failed:', err);
            setStatus({ type: 'error', message: `Submission failed: ${err.message}` });
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="max-w-xl mx-auto">
            <div className="mb-6">
                <h1 className="text-xl font-semibold text-gray-100">Intake Form</h1>
                <p className="text-sm text-gray-500 mt-0.5">
                    Define your offering and ideal customer profile to feed the GTM pipeline
                </p>
            </div>

            <form onSubmit={handleSubmit} className="card space-y-4">
                {status.message && (
                    <div className={`p-3 rounded text-xs ${status.type === 'success' ? 'bg-emerald-950/30 text-emerald-400 border border-emerald-900/30' : 'bg-red-950/30 text-red-400 border border-red-900/30'}`}>
                        {status.message}
                    </div>
                )}

                {/* ── Our Company Name ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Our Company Name
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="ourCompanyName"
                        value={formData.ourCompanyName}
                        onChange={handleChange}
                        placeholder="e.g. CloudLabs"
                        required
                    />
                </div>

                {/* ── Our Services ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Our Services
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="ourServices"
                        value={formData.ourServices}
                        onChange={handleChange}
                        placeholder="e.g. AI Consulting, Cloud Migration"
                        required
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        Used for email personalisation only — not sent to Apollo search
                    </p>
                </div>

                {/* ── Target Location ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Target Location
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="targetLocation"
                        value={formData.targetLocation}
                        onChange={handleChange}
                        placeholder="e.g. United States, India"
                        required
                    />
                </div>

                {/* ── Target Industries (Optional) ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Target Industries
                        <span className="ml-1.5 text-gray-500 font-normal">(Optional)</span>
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="targetIndustries"
                        value={formData.targetIndustries}
                        onChange={handleChange}
                        placeholder="e.g. SaaS, Fintech, Healthcare"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        Leave blank to search across all industries
                    </p>
                </div>

                {/* ── Target Company Size ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Target Company Size
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="targetCompanySize"
                        value={formData.targetCompanySize}
                        onChange={handleChange}
                        placeholder="e.g. 50-5000  (min employees – max employees)"
                        required
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        All company sizes within this range will be included
                    </p>
                </div>

                {/* ── Target Keywords (Optional) ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Target Keywords
                        <span className="ml-1.5 text-gray-500 font-normal">(Optional)</span>
                    </label>
                    <input
                        className="input"
                        type="text"
                        name="targetKeywords"
                        value={formData.targetKeywords}
                        onChange={handleChange}
                        placeholder="e.g. kubernetes, machine learning, digital transformation"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                        Signals used to narrow prospect companies
                    </p>
                </div>

                {/* ── Target Job Titles ── */}
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">
                        Target Job Titles
                    </label>
                    <textarea
                        className="input min-h-[80px]"
                        name="targetJobTitles"
                        value={formData.targetJobTitles}
                        onChange={handleChange}
                        placeholder="e.g. CTO, VP Engineering, Head of AI"
                        required
                    />
                </div>

                <button
                    className="btn-primary w-full mt-2"
                    type="submit"
                    disabled={submitting}
                >
                    {submitting ? 'Submitting...' : 'Start GTM Pipeline'}
                </button>
            </form>
        </div>
    );
}

export default InputForm;