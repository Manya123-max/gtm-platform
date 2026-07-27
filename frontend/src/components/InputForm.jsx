import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const API_URL = 'http://localhost:8000';

function InputForm() {
    const navigate = useNavigate();
    const [formData, setFormData] = useState({
        companyName: '',
        companySize: '',
        services: '',
        location: '',
        jobTitle: '',
        keywords: '',
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
            company_name: formData.companyName,
            company_size: formData.companySize,
            services: formData.services,
            location: formData.location,
            job_title: formData.jobTitle,
            keywords: formData.keywords,
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
            setStatus({ type: 'success', message: 'Company details submitted successfully! Redirecting to Agent Control...' });
            
            // Reset form fields
            setFormData({
                companyName: '',
                companySize: '',
                services: '',
                location: '',
                jobTitle: '',
                keywords: '',
            });

            setTimeout(() => {
                navigate('/agents');
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
                <p className="text-sm text-gray-500 mt-0.5">Submit your company and target audience details to feed the GTM pipeline</p>
            </div>

            <form onSubmit={handleSubmit} className="card space-y-4">
                {status.message && (
                    <div className={`p-3 rounded text-xs ${status.type === 'success' ? 'bg-emerald-950/30 text-emerald-400 border border-emerald-900/30' : 'bg-red-950/30 text-red-400 border border-red-900/30'}`}>
                        {status.message}
                    </div>
                )}

                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Company Name</label>
                    <input
                        className="input"
                        type="text"
                        name="companyName"
                        value={formData.companyName}
                        onChange={handleChange}
                        placeholder="e.g. Acme Corp"
                        required
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Company Size</label>
                    <input
                        className="input"
                        type="text"
                        name="companySize"
                        value={formData.companySize}
                        onChange={handleChange}
                        placeholder="e.g. 50-200"
                        required
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Services Offered</label>
                    <input
                        className="input"
                        type="text"
                        name="services"
                        value={formData.services}
                        onChange={handleChange}
                        placeholder="e.g. AI Consulting, Cloud Migrations"
                        required
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Location</label>
                    <input
                        className="input"
                        type="text"
                        name="location"
                        value={formData.location}
                        onChange={handleChange}
                        placeholder="e.g. United States"
                        required
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Target Job Title</label>
                    <input
                        className="input"
                        type="text"
                        name="jobTitle"
                        value={formData.jobTitle}
                        onChange={handleChange}
                        placeholder="e.g. CTO, VP of Engineering"
                        required
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-gray-400 mb-1.5">Keywords</label>
                    <textarea
                        className="input min-h-[80px]"
                        name="keywords"
                        value={formData.keywords}
                        onChange={handleChange}
                        placeholder="e.g. Kubernetes, AWS, machine learning"
                        required
                    />
                </div>

                <button 
                    className="btn-primary w-full mt-2" 
                    type="submit"
                    disabled={submitting}
                >
                    {submitting ? 'Submitting...' : 'Submit Details'}
                </button>
            </form>
        </div>
    );
}

export default InputForm;