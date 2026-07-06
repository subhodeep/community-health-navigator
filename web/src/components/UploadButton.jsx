import React, { useRef, useState } from 'react';
import { uploadImage } from '../api.js';

export default function UploadButton({ persona, disabled, onUploaded, onError }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const handleChange = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = ''; // allow re-selecting the same file
    if (!file) return;
    setUploading(true);
    try {
      const gcsUri = await uploadImage(file, persona);
      onUploaded(gcsUri, file.name);
    } catch (err) {
      onError(err.message || 'Image upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="visually-hidden"
        onChange={handleChange}
        tabIndex={-1}
        aria-hidden="true"
      />
      <button
        type="button"
        className="upload-btn"
        aria-label="Attach an image"
        title="Attach an image"
        disabled={disabled || uploading}
        onClick={() => inputRef.current && inputRef.current.click()}
      >
        {uploading ? '…' : '📷'}
      </button>
    </>
  );
}
