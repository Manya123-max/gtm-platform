import React, { useState, useRef, useEffect } from 'react';

export default function SearchableMultiSelect({
    label,
    options = [],
    selectedValues = [],
    onChange,
    placeholder = 'Search or select options...',
    helperText,
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [search, setSearch] = useState('');
    const containerRef = useRef(null);

    useEffect(() => {
        function handleClickOutside(event) {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Check if options are rich objects or plain strings
    const isObjectOptions = options.length > 0 && typeof options[0] === 'object';

    // Normalize option getter
    const getOptName = (opt) => (isObjectOptions ? opt.name : opt);

    // Filter options matching search query across name, group, or description
    const filteredOptions = options.filter(opt => {
        const query = search.toLowerCase().trim();
        if (!query) return true;
        if (isObjectOptions) {
            return (
                opt.name.toLowerCase().includes(query) ||
                (opt.group && opt.group.toLowerCase().includes(query)) ||
                (opt.description && opt.description.toLowerCase().includes(query)) ||
                (opt.targetObject && opt.targetObject.toLowerCase().includes(query))
            );
        }
        return opt.toLowerCase().includes(query);
    });

    // Group options if they contain a `group` attribute
    const groupedOptions = React.useMemo(() => {
        if (!isObjectOptions) return null;
        const groups = {};
        filteredOptions.forEach(opt => {
            const grp = opt.group || 'Other';
            if (!groups[grp]) groups[grp] = [];
            groups[grp].push(opt);
        });
        return groups;
    }, [filteredOptions, isObjectOptions]);

    const toggleOption = (optName) => {
        if (selectedValues.includes(optName)) {
            onChange(selectedValues.filter(v => v !== optName));
        } else {
            onChange([...selectedValues, optName]);
        }
    };

    const removeOption = (val, e) => {
        e.stopPropagation();
        onChange(selectedValues.filter(v => v !== val));
    };

    // Check if user selected any options requiring external integrations / sequence history
    const hasUnsupportedSelected = isObjectOptions && selectedValues.some(val => {
        const found = options.find(o => o.name === val);
        return found && found.supported === false;
    });

    const getBadgeStyle = (supportStatus) => {
        switch (supportStatus) {
            case 'supported':
                return 'bg-emerald-50 text-emerald-700 border-emerald-200';
            case 'partial':
                return 'bg-indigo-50 text-indigo-700 border-indigo-200';
            case 'requires_addon':
            case 'requires_plays':
                return 'bg-amber-50 text-amber-700 border-amber-200';
            case 'requires_crm':
                return 'bg-purple-50 text-purple-700 border-purple-200';
            case 'requires_sequence':
            default:
                return 'bg-slate-100 text-slate-600 border-slate-200';
        }
    };

    return (
        <div className="relative" ref={containerRef}>
            <label className="block text-xs font-bold text-[#1E1B4B] mb-2">
                {label} <span className="text-gray-400 font-normal">(Optional)</span>
            </label>

            {/* Selected Chips */}
            {selectedValues.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-2">
                    {selectedValues.map(val => (
                        <span
                            key={val}
                            className="inline-flex items-center gap-1 bg-[#EEF2FF] text-[#4F46E5] border border-[#C7D2FE] px-2.5 py-1 rounded-lg text-[11px] font-medium shadow-xs"
                        >
                            <span>{val}</span>
                            <button
                                type="button"
                                onClick={(e) => removeOption(val, e)}
                                className="text-[#6366F1] hover:text-[#4338CA] focus:outline-none cursor-pointer font-bold text-xs ml-0.5"
                                title="Remove filter"
                            >
                                ×
                            </button>
                        </span>
                    ))}
                </div>
            )}

            {/* Trigger Button / Input Bar */}
            <div
                onClick={() => setIsOpen(!isOpen)}
                className="w-full bg-[#FBFBFE] hover:bg-white focus-within:bg-white border border-[#ECE8FE] hover:border-[#D6CEFC] focus-within:border-[#5B4EFF] rounded-xl py-2.5 px-3 text-xs sm:text-[13px] text-gray-800 cursor-pointer flex items-center justify-between transition-all shadow-sm"
            >
                <span className={selectedValues.length === 0 ? "text-gray-400" : "text-gray-700 font-medium"}>
                    {selectedValues.length === 0
                        ? placeholder
                        : `${selectedValues.length} selected`}
                </span>
                <svg
                    className={`w-4 h-4 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                </svg>
            </div>

            {/* Dropdown Menu */}
            {isOpen && (
                <div className="absolute z-30 left-0 right-0 mt-1.5 bg-white border border-[#ECE8FE] rounded-xl shadow-xl p-2.5 space-y-2 max-h-72 overflow-y-auto">
                    {/* Search Field */}
                    <div className="sticky top-0 bg-white pb-1.5 pt-0.5 border-b border-gray-100 z-10">
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Type to filter..."
                            autoFocus
                            onClick={(e) => e.stopPropagation()}
                            className="w-full bg-[#F8FAFC] border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-[#5B4EFF]"
                        />
                    </div>

                    {/* Grouped or Flat Options List */}
                    {isObjectOptions && groupedOptions ? (
                        Object.keys(groupedOptions).length === 0 ? (
                            <div className="text-[11px] text-gray-400 p-3 text-center">
                                No matching signals found
                            </div>
                        ) : (
                            Object.entries(groupedOptions).map(([groupName, groupItems]) => (
                                <div key={groupName} className="space-y-1">
                                    <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400 px-2 pt-1.5 pb-0.5">
                                        {groupName}
                                    </div>
                                    {groupItems.map((opt) => {
                                        const checked = selectedValues.includes(opt.name);
                                        return (
                                            <div
                                                key={opt.name}
                                                onClick={() => toggleOption(opt.name)}
                                                className={`flex items-start gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors ${
                                                    checked ? 'bg-[#EEF2FF] border border-[#C7D2FE]/60' : 'hover:bg-gray-50 border border-transparent'
                                                }`}
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={checked}
                                                    onChange={() => {}}
                                                    className="w-3.5 h-3.5 mt-0.5 rounded border-gray-300 text-[#5B4EFF] focus:ring-[#5B4EFF] pointer-events-none"
                                                />
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center gap-1.5 flex-wrap">
                                                        <span className={`font-medium ${checked ? 'text-[#4F46E5]' : 'text-gray-800'}`}>
                                                            {opt.name}
                                                        </span>
                                                        {opt.targetObject && (
                                                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-gray-100 text-gray-500 font-medium">
                                                                {opt.targetObject}
                                                            </span>
                                                        )}
                                                        {opt.supportBadge && (
                                                            <span className={`text-[9px] px-1.5 py-0.2 rounded border font-medium ${getBadgeStyle(opt.supportStatus)}`}>
                                                                {opt.supportBadge}
                                                            </span>
                                                        )}
                                                    </div>
                                                    {opt.description && (
                                                        <p className="text-[11px] text-gray-400 mt-0.5 leading-snug">
                                                            {opt.description}
                                                        </p>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ))
                        )
                    ) : (
                        /* Flat Options List (e.g. Funding stages) */
                        <div className="space-y-0.5">
                            {filteredOptions.length === 0 ? (
                                <div className="text-[11px] text-gray-400 p-2 text-center">
                                    No matching options found
                                </div>
                            ) : (
                                filteredOptions.map((opt) => {
                                    const optName = getOptName(opt);
                                    const checked = selectedValues.includes(optName);
                                    return (
                                        <div
                                            key={optName}
                                            onClick={() => toggleOption(optName)}
                                            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg cursor-pointer text-xs transition-colors ${
                                                checked ? 'bg-[#EEF2FF] text-[#4F46E5] font-medium' : 'hover:bg-gray-50 text-gray-700'
                                            }`}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={checked}
                                                onChange={() => {}}
                                                className="w-3.5 h-3.5 rounded border-gray-300 text-[#5B4EFF] focus:ring-[#5B4EFF] pointer-events-none"
                                            />
                                            <span>{optName}</span>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Informational Diagnostic Banner when Integration-Dependent Signals are selected */}
            {hasUnsupportedSelected && (
                <div className="mt-2 p-2.5 rounded-lg bg-amber-50/80 border border-amber-200/80 text-[11px] text-amber-800 flex items-start gap-1.5">
                    <span className="font-bold text-amber-700">ℹ</span>
                    <span>
                        <strong>Note:</strong> Selected Persona, Engagement, or Intent signals require connected CRM data or active Apollo sequence history. Only supported company momentum criteria are applied during cold prospect search.
                    </span>
                </div>
            )}

            {helperText && (
                <p className="text-[11px] text-gray-400 mt-1.5 font-normal">
                    {helperText}
                </p>
            )}
        </div>
    );
}
