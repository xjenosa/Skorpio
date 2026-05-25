import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { ScrollIndicator, useSmoothScroll } from '../components/SmoothStage'
import './LegalPage.css'

const LOGO = (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true">
    <rect width="32" height="32" rx="7" fill="#1f1e1d"/>
    <g transform="translate(6.25, 3) scale(0.8125)">
      <path d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z" fill="#F38764"/>
    </g>
  </svg>
)

export function PrivacyPolicyPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  useSmoothScroll(scrollRef)
  return (
    <div ref={scrollRef} className="legal-root smooth-scroll">
      <header className="topbar">
        <span />
        <Link className="brand" to="/login" aria-label="Skorpio">
          {LOGO}
          <span className="wordmark">SKORPIO</span>
        </Link>
        <Link className="back" to="/login">← Back to sign in</Link>
      </header>

      <main className="content">
        <div className="eyebrow">Legal · Privacy</div>
        <h1>Privacy Policy</h1>
        <p className="meta">Effective date: May 16, 2025 · Last updated: May 16, 2025</p>

        <p>
          Skorpio Operator Console ("<strong>Skorpio</strong>," "<strong>we</strong>,"
          "<strong>our</strong>") is a grid-analysis platform built for energy operators,
          infrastructure teams, and researchers. This Privacy Policy explains what information
          we collect when you use the service, how we use and protect it, and your rights with
          respect to that information.
        </p>
        <p>
          By accessing or using Skorpio you agree to the practices described below. If you do
          not agree, please do not use the service.
        </p>

        <div className="section-divider" />

        <h2>1. Information We Collect</h2>
        <p><strong>Account information.</strong> When you create an account we collect your email
        address and, if you sign in with Google, the public profile information returned by Google
        OAuth (name, profile picture URL, and a Google-assigned identifier). We do not store your
        Google password.</p>

        <p><strong>Usage data.</strong> We record the analyses you run, including the pipeline type
        you selected (e.g., Datacenter Siting, Winter Peak Stress Test), the parameters you submitted,
        and the results returned. This data is stored so you can revisit past sessions from the
        Reports tab and so we can improve the quality of the models.</p>

        <p><strong>Log and technical data.</strong> Our servers automatically record standard web
        log information: IP address, browser type, operating system, referring URL, pages visited,
        and the date and time of each request. We also capture error traces when the application
        encounters an unexpected failure.</p>

        <p><strong>Communications.</strong> If you contact us by email we retain a copy of that
        correspondence to help resolve your issue.</p>

        <h2>2. How We Use Your Information</h2>
        <ul>
          <li><strong>Provide the service.</strong> Authenticate your session, run the analysis
          pipelines you request, and return results.</li>
          <li><strong>Improve and develop features.</strong> Aggregate, anonymised usage patterns
          help us understand which pipelines are used most and where results can be made more
          accurate.</li>
          <li><strong>Security and fraud prevention.</strong> Log data helps us detect abuse,
          investigate incidents, and enforce our Terms of Use.</li>
          <li><strong>Legal obligations.</strong> We may retain or disclose information when
          required by applicable law, regulation, or a valid government order.</li>
        </ul>
        <p>We do not sell, rent, or trade your personal information to third parties for their
        own marketing purposes.</p>

        <h2>3. Cookies and Local Storage</h2>
        <p>Skorpio stores a signed session token in your browser's <code>localStorage</code> under
        the key <code>skorpio.auth.token</code> to keep you signed in across page refreshes. We do
        not use third-party advertising cookies. Standard server-side session cookies may be set by
        the authentication flow.</p>

        <h2>4. Third-Party Services</h2>
        <p><strong>Google OAuth.</strong> If you choose "Continue with Google," your browser is
        redirected to Google's authentication servers. Google's own privacy policy governs
        information collected during that redirect. We receive only the profile fields your Google
        account grants us.</p>

        <p><strong>Anthropic Claude API.</strong> Analysis pipelines may transmit your workload
        parameters to Claude (Anthropic PBC) to generate structured reports. Anthropic's data-use
        policy applies to those API calls. We do not send your email address or account credentials
        to Claude.</p>

        <p><strong>Electricity Maps / Weather APIs.</strong> Certain live-data widgets call
        third-party data providers. Only the grid zone or city name required to fetch the data is
        transmitted; no personal information is included.</p>

        <h2>5. Data Retention</h2>
        <p>Job results are retained indefinitely unless you delete them from the Reports tab or
        request deletion of your account. Account records are retained for as long as your account
        exists and for a reasonable period afterwards to satisfy legal obligations. You may request
        deletion of your account and associated data at any time by emailing us.</p>

        <h2>6. Security</h2>
        <p>We implement industry-standard controls (encrypted transport via TLS, hashed credentials,
        and access controls) to protect your data. No method of transmission over the Internet is
        completely secure, and we cannot guarantee absolute security.</p>

        <h2>7. Children's Privacy</h2>
        <p>Skorpio is not directed at children under 13. We do not knowingly collect personal
        information from children. If you believe a child has provided us with personal
        information, please contact us and we will delete it.</p>

        <h2>8. Changes to This Policy</h2>
        <p>We may update this Privacy Policy from time to time. When we do, we will revise the
        "Last updated" date at the top of this page. Continued use of Skorpio after changes
        are posted constitutes your acceptance of the updated policy.</p>

        <h2>9. Contact Us</h2>
        <p>If you have questions about this policy or want to exercise any data rights, please
        contact the Skorpio team. We will respond within a reasonable timeframe.</p>
      </main>
      <ScrollIndicator targetRef={scrollRef} />
    </div>
  )
}
