import React, { useState } from 'react';
import { Upload, Calendar, FileSpreadsheet, FileText, Loader2 } from 'lucide-react';

interface ImportFormProps {
  onImportStart: (targetDate: string, scanFile: File | null, excelFile: File | null, sheetName: string) => Promise<void>;
  targetDate: string;
  onTargetDateChange: (targetDate: string) => void;
  isLoading: boolean;
}

export const ImportForm: React.FC<ImportFormProps> = ({ onImportStart, targetDate, onTargetDateChange, isLoading }) => {
  const [scanFile, setScanFile] = useState<File | null>(null);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [sheetName, setSheetName] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    if (!targetDate) {
      setValidationError('対象日を選択してください。');
      return;
    }

    if (excelFile && !sheetName.trim()) {
      setValidationError('計画Excelファイルを指定する場合はシート名を入力してください。');
      return;
    }

    try {
      await onImportStart(targetDate, scanFile, excelFile, sheetName.trim());
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
            onInput={(e) => onTargetDateChange(e.currentTarget.value)}
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

          <div className="form-group">
            <label className="form-label" htmlFor="sheet-name">
              <FileSpreadsheet size={16} className="label-icon" />
              シート名 <span className={excelFile ? 'required' : ''}>*</span>
            </label>
            <input
              id="sheet-name"
              type="text"
              className="form-control"
              placeholder="例: 計画"
              value={sheetName}
              onChange={(e) => setSheetName(e.target.value)}
              disabled={isLoading}
            />
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
