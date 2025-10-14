import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import axiosRetry from 'axios-retry';

// Configure axios-retry for handling temporary server downtimes
axiosRetry(axios, {
  retries: 3,
  retryDelay: (retryCount) => retryCount * 1000,
  retryCondition: (error) => {
    return error.code === 'ECONNREFUSED' || !error.response;
  },
});

function App() {
  const [file, setFile] = useState(null);
  const [summary, setSummary] = useState('');
  const [conversationSummary, setConversationSummary] = useState('');
  const [error, setError] = useState('');
  const [userMessage, setUserMessage] = useState('');
  const [chatLog, setChatLog] = useState([]);
  const [documentId, setDocumentId] = useState('');
  const [filename, setFilename] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const chatContainerRef = useRef(null);

  // Auto-scroll chat to bottom on new messages
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatLog]);

  const checkServerHealth = async () => {
    try {
      await axios.get('http://localhost:5001/health', { timeout: 2000 });
      return true;
    } catch {
      return false;
    }
  };

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setError('');
    setUploadStatus(null);
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file to upload.');
      setUploadStatus('failed');
      return;
    }

    setIsUploading(true);
    setError('');
    setUploadStatus(null);

    const isServerUp = await checkServerHealth();
    if (!isServerUp) {
      setError('Backend server is not running.');
      setIsUploading(false);
      setUploadStatus('failed');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      const uploadRes = await axios.post('http://localhost:5001/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
      });

      setSummary(uploadRes.data.summary || 'No summary available.');
      setDocumentId(uploadRes.data.case_id || '');
      setFilename(uploadRes.data.filename || file.name);
      setChatLog([]);
      setConversationSummary('');
      setError('');
      setUploadStatus('success');
    } catch (err) {
      setError(err.response?.data?.error || 'An error occurred during upload.');
      setUploadStatus('failed');
    } finally {
      setIsUploading(false);
    }
  };

  const handleSendMessage = async () => {
    if (!userMessage.trim()) return;

    const newChatLog = [...chatLog, { role: 'user', content: userMessage }];
    setChatLog(newChatLog);
    setUserMessage('');
    setError('');

    try {
      const res = await axios.post('http://localhost:5001/chat', {
        message: userMessage,
        case_id: documentId,
      });

      const reply = res.data.reply;
      const updatedChatLog = [...newChatLog, { role: 'assistant', content: reply }];
      setChatLog(updatedChatLog);
    } catch (err) {
      setChatLog([...newChatLog, { role: 'assistant', content: 'Error processing your request.' }]);
      setError('Error sending message.');
    }
  };

  const generateConversationSummary = async () => {
    if (chatLog.length === 0) return;

    try {
      const summaryRes = await axios.post('http://localhost:5001/conversation_summary', {
        chat: chatLog,
        case_id: documentId,
      });
      setConversationSummary(summaryRes.data.summary || 'No summary available.');
    } catch {
      setConversationSummary('Could not generate conversation summary.');
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: '#f5f5f5',
        fontFamily: "'Arial', sans-serif",
        color: '#2c3e50',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
      }}
    >
      {/* Header */}
      <header
        style={{
          width: '100%',
          maxWidth: '1200px',
          backgroundColor: '#2c3e50',
          padding: '15px 30px',
          borderBottom: '3px solid #d4af37',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 2px 10px rgba(0,0,0,0.1)',
          marginBottom: '30px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: '28px', marginRight: '15px' }}>⚖️</span>
          <h1
            style={{
              fontFamily: "'Georgia', serif",
              fontSize: '28px',
              color: '#ffffff',
              margin: 0,
              textTransform: 'uppercase',
              letterSpacing: '1px',
            }}
          >
            Court Document Analyzer
          </h1>
        </div>
      </header>

      {/* Main */}
      <main style={{ width: '100%', maxWidth: '1200px', display: 'flex', gap: '20px' }}>
        {/* Left Column: Upload + Summary */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Upload Section */}
          <section
            style={{
              padding: '20px',
              border: '1px solid #d4af37',
              borderRadius: '6px',
              backgroundColor: '#f9f9f9',
            }}
          >
            <h2
              style={{
                fontFamily: "'Georgia', serif",
                fontSize: '22px',
                color: '#2c3e50',
                marginBottom: '15px',
                borderBottom: '2px solid #d4af37',
                paddingBottom: '5px',
              }}
            >
              Upload Case Document
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '15px', marginBottom: '15px' }}>
              <input
                type="file"
                accept=".pdf,.docx"
                onChange={handleFileChange}
                style={{
                  padding: '10px',
                  border: '1px solid #2c3e50',
                  borderRadius: '4px',
                  backgroundColor: '#ffffff',
                  fontSize: '14px',
                  flex: 1,
                }}
              />
              <button
                onClick={handleUpload}
                disabled={isUploading}
                style={{
                  padding: '10px 20px',
                  backgroundColor: isUploading ? '#7f8c8d' : '#2c3e50',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: '14px',
                  cursor: isUploading ? 'not-allowed' : 'pointer',
                }}
              >
                {isUploading ? 'Uploading...' : 'Upload & Analyze'}
              </button>
            </div>
            {error && <p style={{ color: '#c0392b', fontSize: '14px' }}>{error}</p>}
          </section>

          {/* Case Summary */}
          {summary && (
            <section
              style={{
                padding: '20px',
                border: '1px solid #d4af37',
                borderRadius: '6px',
                backgroundColor: '#f9f9f9',
                height: '200px',
                overflowY: 'auto',
              }}
            >
              <h2
                style={{
                  fontFamily: "'Georgia', serif",
                  fontSize: '22px',
                  color: '#2c3e50',
                  marginBottom: '15px',
                  borderBottom: '2px solid #d4af37',
                  paddingBottom: '5px',
                }}
              >
                Case Summary
              </h2>
              <p
                style={{
                  padding: '15px',
                  border: '1px solid #bdc3c7',
                  borderRadius: '4px',
                  backgroundColor: '#ffffff',
                  whiteSpace: 'pre-wrap',
                  fontSize: '14px',
                  lineHeight: '1.6',
                }}
              >
                {summary}
              </p>
            </section>
          )}

          {/* Conversation Summary */}
          {chatLog.length > 0 && (
            <section
              style={{
                padding: '20px',
                border: '1px solid #d4af37',
                borderRadius: '6px',
                backgroundColor: '#f9f9f9',
                height: '150px',
                overflowY: 'auto',
              }}
            >
              <h2
                style={{
                  fontFamily: "'Georgia', serif",
                  fontSize: '22px',
                  color: '#2c3e50',
                  marginBottom: '15px',
                  borderBottom: '2px solid #d4af37',
                  paddingBottom: '5px',
                }}
              >
                Conversation Summary
              </h2>
              <p
                style={{
                  padding: '10px',
                  backgroundColor: '#ffffff',
                  borderRadius: '4px',
                  fontSize: '14px',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {conversationSummary || 'No summary yet.'}
              </p>
            </section>
          )}
        </div>

        {/* Right Column: Chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '20px', height: '100%' }}>
          <section
            style={{
              padding: '20px',
              border: '1px solid #d4af37',
              borderRadius: '6px',
              backgroundColor: '#f9f9f9',
              display: 'flex',
              flexDirection: 'column',
              flexGrow: 1,
            }}
          >
            <h2
              style={{
                fontFamily: "'Georgia', serif",
                fontSize: '22px',
                color: '#2c3e50',
                marginBottom: '15px',
                borderBottom: '2px solid #d4af37',
                paddingBottom: '5px',
              }}
            >
              Chat
            </h2>
            <div
              ref={chatContainerRef}
              style={{ flexGrow: 1, overflowY: 'auto', marginBottom: '15px' }}
            >
              {chatLog.map((msg, idx) => (
                <div key={idx} style={{ marginBottom: '10px', textAlign: msg.role === 'user' ? 'right' : 'left' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      padding: '8px 12px',
                      borderRadius: '12px',
                      backgroundColor: msg.role === 'user' ? '#2c3e50' : '#bdc3c7',
                      color: msg.role === 'user' ? '#ffffff' : '#2c3e50',
                      maxWidth: '80%',
                    }}
                  >
                    {msg.content}
                  </span>
                </div>
              ))}
            </div>

            {/* Input + Buttons */}
            <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
              <input
                type="text"
                value={userMessage}
                onChange={(e) => setUserMessage(e.target.value)}
                style={{ flexGrow: 1, padding: '10px', border: '1px solid #2c3e50', borderRadius: '4px', fontSize: '14px' }}
                placeholder="Type your message..."
              />
              <button
                onClick={handleSendMessage}
                style={{ padding: '10px 20px', backgroundColor: '#2c3e50', color: '#ffffff', border: 'none', borderRadius: '4px', fontSize: '14px' }}
              >
                Send
              </button>
            </div>

            {/* Generate Conversation Summary Button */}
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '10px' }}>
              <button
                onClick={generateConversationSummary}
                style={{
                  padding: '10px 20px',
                  backgroundColor: '#d4af37',
                  color: '#2c3e50',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: '14px',
                  cursor: 'pointer',
                }}
              >
                Generate Conversation Summary
              </button>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;
