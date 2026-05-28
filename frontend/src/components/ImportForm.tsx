import React, { useState } from 'react';
import { Upload, Calendar, FileSpreadsheet, FileText, Loader2 } from 'lucide-react';

interface ImportFormProps {
  onImportStart: (targetDate: string, scanFile: File | null, excelFile: File | null) => Promise<void>;
  isLoading: boolean;
}

export const ImportForm: React.FC<ImportFormProps> = ({ onImportStart, isLoading }) => {
  // Set default target date to today in YYYY-MM-DD format (Tokyo Time zone standard)
  const getTodayString = () => {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  };

  const [targetDate, setTargetDate] = useState<string>(getTodayString());
  const [scanFile, setScanFile] = useState<File | null>(null);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    if (!targetDate) {
      setValidationError('対象日を選択してください。');
      return;
    }

    try {
      await onImportStart(targetDate, scanFile, excelFile);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="card form-card">
      <h2 className="card-title">
        <Upload className="icon-title" size={20} />
        作業計画・OCR 取込
      </h2>
      
      <form onSubmit={handleSubmit} className="import-form">
        <div className="form-group">
          <label className="form-label" htmlFor="target-date">
            <Calendar size={16} className="label-icon" />
            対象日 <span className="required">*</span>
          </label>
          <input
            id="target-date"
            type="date"
            className="form-control"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            disabled={isLoading}
            required
          />
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label className="form-label" htmlFor="scan-file">
              <FileText size={16} className="label-icon" />
              OCRスキャンファイル (PDFまたはテキスト)
            </label>
            <div className={`file-upload-wrapper ${scanFile ? 'has-file' : ''}`}>
              <input
                id="scan-file"
                type="file"
                className="file-input-hidden"
                accept=".pdf,.txt"
                onChange={(e) => setScanFile(e.target.files?.[0] || null)}
                disabled={isLoading}
              />
              <label htmlFor="scan-file" className="file-upload-label">
                <span className="upload-btn">ファイルを選択</span>
                <span className="file-name-display">
                  {scanFile ? scanFile.name : '選択されていません (PDF / TXT)'}
                </span>
              </label>
              {scanFile && (
                <button
                  type="button"
                  className="clear-file-btn"
                  onClick={() => setScanFile(null)}
                  disabled={isLoading}
                >
                  &times;
                </button>
              )}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="excel-file">
              <FileSpreadsheet size={16} className="label-icon" />
              計画Excelファイル
            </label>
            <div className={`file-upload-wrapper ${excelFile ? 'has-file' : ''}`}>
              <input
                id="excel-file"
                type="file"
                className="file-input-hidden"
                accept=".xlsx,.xls,.xlsm"
                onChange={(e) => setExcelFile(e.target.files?.[0] || null)}
                disabled={isLoading}
              />
              <label htmlFor="excel-file" className="file-upload-label">
                <span className="upload-btn">ファイルを選択</span>
                <span className="file-name-display">
                  {excelFile ? excelFile.name : '選択されていません (Excel)'}
                </span>
              </label>
              {excelFile && (
                <button
                  type="button"
                  className="clear-file-btn"
                  onClick={() => setExcelFile(null)}
                  disabled={isLoading}
                >
                  &times;
                </button>
              )}
            </div>
          </div>
        </div>

        {validationError && (
          <div className="validation-error-alert">
            {validationError}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary btn-submit"
          disabled={isLoading || !targetDate}
        >
          {isLoading ? (
            <>
              <Loader2 className="animate-spin mr-2" size={18} />
              処理中...
            </>
          ) : (
            '取込を実行する'
          )}
        </button>
      </form>
    </div>
  );
};
