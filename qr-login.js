export default async function handler(req, res) {
    // CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const { action, userAgent, code, cookies } = req.body;

    try {
        switch (action) {
            case 'generate':
                const qrResult = await generateQR(userAgent);
                return res.json(qrResult);

            case 'check':
                const checkResult = await checkQRStatus(code);
                return res.json(checkResult);

            case 'get-data':
                const dataResult = await getIMEIAndCookies(code, userAgent, cookies);
                return res.json(dataResult);

            default:
                return res.status(400).json({ error: 'Invalid action' });
        }
    } catch (error) {
        console.error('API Error:', error);
        return res.status(500).json({
            status: 'error',
            message: error.message || 'Internal server error'
        });
    }
}

// Tạo QR Code (mock - thay bằng API Zalo thật)
async function generateQR(userAgent) {
    // Trong production, gọi API Zalo:
    // 1. GET https://id.zalo.me/account?continue=https%3A%2F%2Fchat.zalo.me%2F
    // 2. Lấy version từ main-xxx.js
    // 3. POST /account/logininfo
    // 4. POST /account/verify-client
    // 5. POST /account/authen/qr/generate
    
    const mockQRCode = 'QR_' + Date.now() + '_' + Math.random().toString(36).substring(7);
    
    // Mock QR image (base64 của 1 QR code mẫu)
    const mockImage = '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';

    return {
        status: 'success',
        code: mockQRCode,
        image: mockImage
    };
}

// Kiểm tra trạng thái QR (mock - thay bằng polling API Zalo thật)
async function checkQRStatus(code) {
    // Trong production, gọi API Zalo:
    // POST /account/authen/qr/waiting-scan
    // POST /account/authen/qr/waiting-confirm
    
    // Mock: giả lập quét sau 5-10 giây
    const scanTime = 5000 + Math.random() * 5000;
    
    await new Promise(resolve => setTimeout(resolve, scanTime));
    
    // Random: 70% thành công, 30% lỗi
    const success = Math.random() < 0.7;
    
    if (success) {
        return {
            status: 'scanned',
            code: code,
            displayName: 'User_' + Math.random().toString(36).substring(7)
        };
    } else {
        return {
            status: 'error',
            message: 'Không thể quét QR, vui lòng thử lại'
        };
    }
}

// Lấy IMEI và Cookie (mock - thay bằng API Zalo thật)
async function getIMEIAndCookies(code, userAgent, cookies) {
    // Trong production:
    // 1. POST /account/authen/qr/confirm
    // 2. GET /account/checksession
    // 3. GET /jr/userinfo
    // 4. GET /api/login/getLoginInfo?imei=...
    // 5. Lấy cookies từ session
    
    const mockIMEI = 'IMEI_' + Date.now() + '_' + Math.random().toString(36).substring(7);
    
    const mockCookies = {
        'zpsid': 's_' + Math.random().toString(36).substring(7),
        'zpc': 'c_' + Math.random().toString(36).substring(7),
        'zpw_sek': 'sek_' + Math.random().toString(36).substring(7),
        '_zpsuid': 'uid_' + Math.random().toString(36).substring(7),
        'zpsid': 's2_' + Math.random().toString(36).substring(7),
        'zpw_ws': 'ws_' + Math.random().toString(36).substring(7)
    };

    return {
        status: 'success',
        data: {
            imei: mockIMEI,
            cookies: mockCookies,
            userAgent: userAgent || navigator.userAgent || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    };
}
